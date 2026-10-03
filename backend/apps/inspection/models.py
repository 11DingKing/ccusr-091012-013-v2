"""
抽检管理模型

抽检方案（SamplingPlan）维护草案、发布、生效区间与撤回；
到场核验（Inspection）在批次到场时固定方案快照，
保存样本数量、检查项与判定，快照一经固定不可变更。
"""
from django.db import models
from apps.authentication.models import User
from apps.warehouse.models import Category


class SamplingPlan(models.Model):
    """抽检方案模型"""

    STATUS_CHOICES = [
        ('draft', '草案'),
        ('published', '已发布'),
        ('withdrawn', '已撤回'),
    ]

    name = models.CharField('方案名称', max_length=50)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT,
        related_name='sampling_plans', verbose_name='物资品类'
    )
    source = models.CharField('适用来源', max_length=100, blank=True,
                              help_text='留空表示适用全部来源')
    min_quantity = models.DecimalField('批量下限', max_digits=12, decimal_places=2, default=0)
    max_quantity = models.DecimalField('批量上限', max_digits=12, decimal_places=2,
                                       null=True, blank=True,
                                       help_text='留空表示不限')
    sample_ratio = models.DecimalField('抽检比例', max_digits=5, decimal_places=4)
    tightened_ratio = models.DecimalField('加严抽检比例', max_digits=5, decimal_places=4)
    min_sample_size = models.PositiveIntegerField('最小样本数', default=1)
    max_sample_size = models.PositiveIntegerField('最大样本数', null=True, blank=True,
                                                  help_text='留空表示不封顶')
    check_items = models.JSONField('检查项', default=list,
                                   help_text='[{"name": "外观", "standard": "无破损"}]')
    priority = models.IntegerField('优先级', default=0,
                                   help_text='规则重叠时数值大者优先')
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='draft')
    effective_from = models.DateTimeField('生效开始时间', null=True, blank=True)
    effective_to = models.DateTimeField('生效截止时间', null=True, blank=True)
    published_at = models.DateTimeField('发布时间', null=True, blank=True)
    published_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='published_sampling_plans', verbose_name='发布人'
    )
    withdrawn_at = models.DateTimeField('撤回时间', null=True, blank=True)
    withdrawn_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='withdrawn_sampling_plans', verbose_name='撤回人'
    )
    withdraw_reason = models.CharField('撤回原因', max_length=200, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_sampling_plans', verbose_name='创建人'
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'insp_sampling_plan'
        verbose_name = '抽检方案'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name}({self.get_status_display()})"

    @property
    def is_editable(self):
        """是否可编辑（仅草案）"""
        return self.status == 'draft'

    def is_effective_at(self, moment):
        """指定时刻是否在生效区间内（区间端点闭区间，留空表示不限）"""
        if self.effective_from and moment < self.effective_from:
            return False
        if self.effective_to and moment > self.effective_to:
            return False
        return True

    def matches(self, source, quantity, moment):
        """判断方案是否适用于指定来源、批量与时刻的批次"""
        if self.status != 'published':
            return False
        if self.source and self.source != source:
            return False
        if quantity < self.min_quantity:
            return False
        if self.max_quantity is not None and quantity > self.max_quantity:
            return False
        return self.is_effective_at(moment)


class Inspection(models.Model):
    """到场核验模型（方案快照）

    批次到场核验时按物资品类、来源和批量匹配抽检方案并冻结快照，
    之后样本数量、检查项与判定均以快照为准；
    同一批次号重复核验返回同一快照，不套用新方案。
    """

    STATUS_CHOICES = [
        ('pending', '待判定'),
        ('completed', '已判定'),
    ]

    LEVEL_CHOICES = [
        ('normal', '正常检验'),
        ('tightened', '加严检验'),
    ]

    CONCLUSION_CHOICES = [
        ('qualified', '合格'),
        ('unqualified', '不合格'),
    ]

    batch_no = models.CharField('批次号', max_length=50, unique=True)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT,
        related_name='inspections', verbose_name='物资品类'
    )
    source = models.CharField('批次来源', max_length=100, blank=True)
    batch_quantity = models.DecimalField('批量', max_digits=12, decimal_places=2)
    plan = models.ForeignKey(
        SamplingPlan, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='inspections', verbose_name='抽检方案'
    )
    plan_snapshot = models.JSONField('方案快照', default=dict,
                                     help_text='固定时刻冻结的方案内容')
    inspection_level = models.CharField('检验严格度', max_length=20,
                                        choices=LEVEL_CHOICES, default='normal')
    tightened_trigger = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='tightened_followups', verbose_name='加严触发记录'
    )
    sample_size = models.PositiveIntegerField('样本数量')
    check_items = models.JSONField('检查项', default=list)
    item_results = models.JSONField('检查项结果', default=list)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    conclusion = models.CharField('判定结论', max_length=20,
                                  choices=CONCLUSION_CHOICES, null=True, blank=True)
    verified_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='inspections', verbose_name='核验人'
    )
    verified_at = models.DateTimeField('到场核验时间')
    completed_at = models.DateTimeField('判定时间', null=True, blank=True)
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'insp_inspection'
        verbose_name = '到场核验'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.batch_no} - {self.get_status_display()}"
