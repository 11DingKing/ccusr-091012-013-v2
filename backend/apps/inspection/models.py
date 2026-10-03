"""
抽检方案管理模型

方案生命周期：草案 draft -> 发布 published（带生效区间）-> 撤回 withdrawn。
到场核验时按物资类别、来源、批量匹配当前生效方案，并把方案全文固化为
快照（InspectionSnapshot），样本数量按固定取整规则当场算出并落库；
检查项逐项复制为快照明细。此后方案的发布新版本或撤回均不影响既有快照，
旧批次再次查询永远返回它当时固定下来的方案，不会套用新方案。
"""
from django.conf import settings
from django.db import models
from django.db.models import Q


# 抽样严格度：正常 / 加严（风险上升后提高抽检比例）
SEVERITY_NORMAL = 'normal'
SEVERITY_TIGHTENED = 'tightened'
SEVERITY_CHOICES = [
    (SEVERITY_NORMAL, '正常'),
    (SEVERITY_TIGHTENED, '加严'),
]

# 方案状态：草案 / 已发布 / 已撤回
PLAN_DRAFT = 'draft'
PLAN_PUBLISHED = 'published'
PLAN_WITHDRAWN = 'withdrawn'
PLAN_STATUS_CHOICES = [
    (PLAN_DRAFT, '草案'),
    (PLAN_PUBLISHED, '已发布'),
    (PLAN_WITHDRAWN, '已撤回'),
]

# 取整规则：向上取整 / 四舍五入 / 向下取整
ROUND_UP = 'up'
ROUND_HALF_UP = 'half_up'
ROUND_DOWN = 'down'
ROUNDING_RULE_CHOICES = [
    (ROUND_UP, '向上取整'),
    (ROUND_HALF_UP, '四舍五入'),
    (ROUND_DOWN, '向下取整'),
]

# 规则优先级（数值越大越优先）：加严规则始终比普通规则优先
PRIORITY_NORMAL = 10
PRIORITY_TIGHTENED = 20

# 判定结论
RESULT_PASS = 'pass'
RESULT_FAIL = 'fail'
RESULT_CONDITIONAL = 'conditional'
RESULT_PENDING = 'pending'
RESULT_CHOICES = [
    (RESULT_PENDING, '待判定'),
    (RESULT_PASS, '合格'),
    (RESULT_FAIL, '不合格'),
    (RESULT_CONDITIONAL, '让步接收'),
]


class SamplingRule(models.Model):
    """
    抽样规则：在某批量区间 [batch_min, batch_max] 内，
    按比例（可为空表示固定数量）抽取样本。

    一个方案可拥有多条规则（正常 + 加严）。同一严格度下批量区间互不重叠，
    跨严格度允许重叠，命中时加严规则优先（见 services.resolve_rule）。
    """
    plan = models.ForeignKey(
        'InspectionPlan', on_delete=models.CASCADE,
        related_name='rules', verbose_name='所属方案'
    )
    severity = models.CharField('严格度', max_length=20, choices=SEVERITY_CHOICES,
                                default=SEVERITY_NORMAL)
    batch_min = models.PositiveIntegerField('批量下限（含）')
    batch_max = models.PositiveIntegerField('批量上限（含，0 表示不限）', default=0)
    sample_ratio = models.DecimalField('抽样比例', max_digits=6, decimal_places=4,
                                       null=True, blank=True,
                                       help_text='如 0.10 表示 10%；与固定数量二选一或同时作为下限')
    fixed_sample_count = models.PositiveIntegerField('固定样本数量', null=True, blank=True)
    min_sample_count = models.PositiveIntegerField('最少样本数', default=1)
    rounding_rule = models.CharField('取整规则', max_length=20,
                                     choices=ROUNDING_RULE_CHOICES, default=ROUND_UP)
    priority = models.PositiveIntegerField('优先级', default=PRIORITY_NORMAL)
    # 加严复检：触发复检时使用的规则（如加倍抽样），为空表示不支持复检
    recheck_rule = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='recheck_sources', verbose_name='加严复检规则'
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'in_sampling_rule'
        verbose_name = '抽样规则'
        verbose_name_plural = verbose_name
        ordering = ['severity', 'batch_min']

    def __str__(self):
        return f'{self.get_severity_display()}-{self.batch_min}~{self.batch_max or "∞"}'


class InspectionItem(models.Model):
    """检查项模板：方案规定要查的项目、检验方法与合格判定阈值"""
    plan = models.ForeignKey(
        'InspectionPlan', on_delete=models.CASCADE,
        related_name='items', verbose_name='所属方案'
    )
    name = models.CharField('检查项名称', max_length=100)
    method = models.CharField('检验方法', max_length=200, blank=True)
    standard = models.CharField('合格标准', max_length=200, blank=True)
    # 关键项不合格直接判不合格；非关键项计入不合格数由方案阈值统一判定
    is_critical = models.BooleanField('是否关键项', default=False)
    sort_order = models.PositiveIntegerField('排序', default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'in_inspection_item'
        verbose_name = '检查项'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.name


class InspectionPlan(models.Model):
    """
    抽检方案。同一适用范围（品类 + 来源）下，任意时刻至多有一个版本处于
    生效状态；发布新版本时同范围旧版本自动失效，撤回则立即终止生效。
    已发布/已撤回的方案内容不可修改，只能以新版本迭代（保证可追溯）。
    """
    code = models.CharField('方案编号', max_length=50, unique=True)
    name = models.CharField('方案名称', max_length=200)
    version = models.CharField('版本号', max_length=20, default='1.0')

    # 适用范围（快照固定时记录这三项的实际取值）
    category = models.ForeignKey(
        'warehouse.Category', on_delete=models.PROTECT,
        related_name='inspection_plans', verbose_name='适用品类'
    )
    source = models.CharField('物资来源', max_length=100, blank=True,
                              help_text='供应商/来源关键字，空串表示适用于全部来源')
    # 风险等级：空表示不限等级；用于“同类物资风险上升后提高抽检比例”，
    # 高风险物资命中加严规则
    risk_level = models.CharField('适用风险等级', max_length=20, blank=True)

    # 判定阈值：样本中不合格数 <= accept_count 判合格，>= reject_count 判不合格，
    # 两者之间判让步接收；关键项任一不合格直接判不合格
    accept_count = models.PositiveIntegerField('合格判定数 Ac', default=0)
    reject_count = models.PositiveIntegerField('不合格判定数 Re', default=1)

    status = models.CharField('状态', max_length=20, choices=PLAN_STATUS_CHOICES,
                              default=PLAN_DRAFT)
    effective_from = models.DateTimeField('生效开始时间', null=True, blank=True)
    effective_to = models.DateTimeField('生效结束时间', null=True, blank=True)
    published_at = models.DateTimeField('发布时间', null=True, blank=True)
    withdrawn_at = models.DateTimeField('撤回时间', null=True, blank=True)
    withdraw_reason = models.CharField('撤回原因', max_length=200, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='inspection_plans', verbose_name='创建人'
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='published_inspection_plans', verbose_name='发布人'
    )
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'in_inspection_plan'
        verbose_name = '抽检方案'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.code} {self.name} v{self.version}'

    @property
    def is_editable(self):
        """只有草案可以编辑"""
        return self.status == PLAN_DRAFT


class InspectionSnapshot(models.Model):
    """
    到场核验时固定下来的方案快照。一个批次（goods + batch_no）只固定一次，
    此后重复查询返回同一快照；方案撤回或升级均不改变快照内容。
    """
    plan = models.ForeignKey(
        InspectionPlan, on_delete=models.PROTECT,
        related_name='snapshots', verbose_name='来源方案'
    )
    goods = models.ForeignKey(
        'warehouse.Goods', on_delete=models.PROTECT,
        related_name='inspection_snapshots', verbose_name='物资'
    )
    batch_no = models.CharField('批次号', max_length=50)

    # 固定时的适用范围留痕（防止品类/来源日后改名导致无法举证）
    category_name = models.CharField('品类名称（快照）', max_length=10)
    source = models.CharField('物资来源（快照）', max_length=100, blank=True)
    risk_level = models.CharField('风险等级（快照）', max_length=20, blank=True)
    batch_quantity = models.PositiveIntegerField('批量', default=0)

    plan_code = models.CharField('方案编号（快照）', max_length=50)
    plan_name = models.CharField('方案名称（快照）', max_length=200)
    plan_version = models.CharField('版本号（快照）', max_length=20)
    severity = models.CharField('实际严格度（快照）', max_length=20,
                                choices=SEVERITY_CHOICES, default=SEVERITY_NORMAL)

    # 当场按固定取整规则算出的样本数量
    sample_count = models.PositiveIntegerField('样本数量')
    rounding_rule = models.CharField('取整规则（快照）', max_length=20,
                                     choices=ROUNDING_RULE_CHOICES)
    accept_count = models.PositiveIntegerField('合格判定数（快照）', default=0)
    reject_count = models.PositiveIntegerField('不合格判定数（快照）', default=1)

    # 方案规则全文留痕
    rule_detail = models.JSONField('命中规则详情（快照）', default=dict)

    fixed_at = models.DateTimeField('固定时间', auto_now_add=True)
    fixed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='fixed_snapshots', verbose_name='固定操作人'
    )

    # 核验结论
    result = models.CharField('判定结论', max_length=20, choices=RESULT_CHOICES,
                              default=RESULT_PENDING)
    judged_at = models.DateTimeField('判定时间', null=True, blank=True)
    judged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='judged_snapshots', verbose_name='判定人'
    )
    judge_remark = models.TextField('判定备注', blank=True)

    # 若启动过加严复检，指向复检快照（首检快照保留原始记录不被覆盖）
    recheck_of = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='rechecks', verbose_name='复检来源快照'
    )

    class Meta:
        db_table = 'in_inspection_snapshot'
        verbose_name = '抽检方案快照'
        verbose_name_plural = verbose_name
        ordering = ['-fixed_at']
        constraints = [
            # 同一批次的首检快照只允许一个；加严复检快照（recheck_of 非空）不受限
            models.UniqueConstraint(
                fields=['goods', 'batch_no'],
                condition=Q(recheck_of__isnull=True),
                name='uniq_first_snapshot_goods_batch',
            ),
            # 一次首检至多发起一次加严复检
            models.UniqueConstraint(
                fields=['recheck_of'],
                condition=Q(recheck_of__isnull=False),
                name='uniq_recheck_per_snapshot',
            ),
        ]

    def __str__(self):
        return f'{self.goods.name}-{self.batch_no}-{self.plan_code}'


class SnapshotItem(models.Model):
    """检查项快照：方案检查项在固定时的逐项副本，记录逐项检验结果"""
    snapshot = models.ForeignKey(
        InspectionSnapshot, on_delete=models.CASCADE,
        related_name='items', verbose_name='所属快照'
    )
    name = models.CharField('检查项名称（快照）', max_length=100)
    method = models.CharField('检验方法（快照）', max_length=200, blank=True)
    standard = models.CharField('合格标准（快照）', max_length=200, blank=True)
    is_critical = models.BooleanField('是否关键项（快照）', default=False)
    sort_order = models.PositiveIntegerField('排序', default=0)
    checked_count = models.PositiveIntegerField('已检数量', default=0)
    defect_count = models.PositiveIntegerField('不合格数量', default=0)
    item_result = models.CharField('单项结论', max_length=20, choices=RESULT_CHOICES,
                                   default=RESULT_PENDING)

    class Meta:
        db_table = 'in_snapshot_item'
        verbose_name = '检查项快照'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f'{self.snapshot_id}-{self.name}'
