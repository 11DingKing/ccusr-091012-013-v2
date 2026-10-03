"""
抽检方案领域服务

集中维护四类一致性逻辑，视图层只做参数编排：
1. 小批量取整：比例 × 批量后按方案固定的取整规则计算，并受最少样本数、
   固定数量和批量本身的上下限约束；
2. 规则重叠：同一严格度下批量区间只允许命中一条规则，重叠即报错，
   跨严格度（正常/加严）允许重叠，命中时加严优先并有正常规则兜底；
3. 生效区间：同适用范围方案的生效区间不允许交叉（发布新版本自动终结
   旧版本），不同精确度（全部来源 vs 指定来源）可并存，取更精确者；
4. 快照固定与撤回：快照一经固定不可改变，方案撤回/升级不影响旧批次，
   加严复检沿用原方案生成复检快照。
"""
import decimal

from django.db import transaction, IntegrityError
from django.db.models import Q, Case, When, IntegerField
from django.utils import timezone

from .models import (
    InspectionPlan, InspectionSnapshot, SnapshotItem, SamplingRule, InspectionItem,
    PLAN_DRAFT, PLAN_PUBLISHED, PLAN_WITHDRAWN,
    SEVERITY_NORMAL, SEVERITY_TIGHTENED,
    ROUND_UP, ROUND_DOWN,
    PRIORITY_NORMAL, PRIORITY_TIGHTENED,
    RESULT_PENDING, RESULT_PASS, RESULT_FAIL, RESULT_CONDITIONAL,
)


class InspectionError(Exception):
    """业务校验错误，message 可直接返回给前端"""


class NoEffectivePlanError(InspectionError):
    """当前到场核验没有生效中的抽检方案"""


class RuleOverlapError(InspectionError):
    """同一严格度下有多条规则同时覆盖该批量"""


class PlanOverlapError(InspectionError):
    """同一精确度下存在多个同时生效的方案"""


# 风险上升时自动加严的风险等级取值
ELEVATED_RISK_LEVELS = {'high', 'elevated', 'tightened', '高', '高风险', '加严'}


# ==================== 取整与样本数量 ====================

def round_sample_count(raw, rounding_rule):
    """按方案固定的取整规则对 比例×批量 的结果取整（Decimal 精确运算）"""
    if isinstance(raw, int):
        return raw
    if rounding_rule == ROUND_UP:
        return int(raw.to_integral_value(rounding=decimal.ROUND_CEILING))
    if rounding_rule == ROUND_DOWN:
        return int(raw.to_integral_value(rounding=decimal.ROUND_FLOOR))
    # 四舍五入（半数进位）
    return int(raw.quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_UP))


def compute_sample_count(rule, batch_quantity):
    """
    根据规则与批量计算样本数量：
    - 同时配置比例与固定数量时取两者较大值（固定数量作为下限）；
    - 最少样本数兜底；样本数不超过批量本身（小批量一致性）。
    """
    if batch_quantity <= 0:
        raise InspectionError('批量必须大于 0')

    if rule.sample_ratio:
        ratio_count = round_sample_count(rule.sample_ratio * batch_quantity,
                                         rule.rounding_rule)
    else:
        ratio_count = None

    if rule.fixed_sample_count is not None and ratio_count is not None:
        count = max(rule.fixed_sample_count, ratio_count)
    elif rule.fixed_sample_count is not None:
        count = rule.fixed_sample_count
    elif ratio_count is not None:
        count = ratio_count
    else:
        raise InspectionError('抽样规则必须配置抽样比例或固定样本数量')

    count = max(count, rule.min_sample_count)
    return min(count, batch_quantity)


# ==================== 规则区间重叠 ====================

def validate_rule_intervals(rules, exclude_pk=None):
    """
    校验同一严格度下批量区间两两不重叠。
    rules: SamplingRule 可迭代对象（草案内全部规则）。
    batch_max == 0 表示上限开放。
    """
    by_severity = {}
    for rule in rules:
        if exclude_pk and rule.pk == exclude_pk:
            continue
        by_severity.setdefault(rule.severity, []).append(rule)

    for severity, group in by_severity.items():
        group.sort(key=lambda r: r.batch_min)
        for prev, cur in zip(group, group[1:]):
            prev_upper = prev.batch_max if prev.batch_max else None
            # 上一区间开放或上限触及下一区间下限（边界含端点，重叠即非法）
            if prev_upper is None or prev_upper >= cur.batch_min:
                raise InspectionError(
                    f'{dict(severity_choices()).get(severity, severity)}规则的批量区间重叠：'
                    f'[{prev.batch_min}, {prev.batch_max or "∞"}] 与 '
                    f'[{cur.batch_min}, {cur.batch_max or "∞"}]'
                )
        for rule in group:
            if rule.batch_max and rule.batch_max < rule.batch_min:
                raise InspectionError('批量上限不能小于下限')


def severity_choices():
    from .models import SEVERITY_CHOICES
    return dict(SEVERITY_CHOICES)


def rule_choices():
    from .models import SEVERITY_CHOICES
    return dict(SEVERITY_CHOICES)


def resolve_rule(plan, batch_quantity, prefer_tightened=False):
    """
    找出覆盖该批量的规则：
    - 同一严格度命中多条 → RuleOverlapError（绝不静默选一条）；
    - 优先加严（要求时），其次正常，最后加严兜底。
    返回 (rule, severity)。
    """
    candidates = list(
        plan.rules
        .filter(batch_min__lte=batch_quantity)
        .filter(Q(batch_max=0) | Q(batch_max__gte=batch_quantity))
    )
    groups = {}
    for rule in candidates:
        groups.setdefault(rule.severity, []).append(rule)

    for severity, matched in groups.items():
        if len(matched) > 1:
            intervals = '、'.join(f'[{r.batch_min},{r.batch_max or "∞"}]' for r in matched)
            raise RuleOverlapError(
                f'批量 {batch_quantity} 同时命中多条{dict(rule_choices()).get(severity)}规则：{intervals}'
            )

    tightened = groups.get(SEVERITY_TIGHTENED)
    normal = groups.get(SEVERITY_NORMAL)
    if prefer_tightened and tightened:
        return tightened[0], SEVERITY_TIGHTENED
    if normal:
        return normal[0], SEVERITY_NORMAL
    if tightened:
        # 正常规则未覆盖该批量时，加严规则兜底
        return tightened[0], SEVERITY_TIGHTENED
    raise InspectionError(f'方案未覆盖批量 {batch_quantity} 的抽样规则')


# ==================== 草案创建 / 更新 ====================

def _validate_recheck_index_graph(rules_data):
    """基于提交序号检测复检规则链：序号越界、自指、成环均拒绝"""
    edges = {}
    for i, row in enumerate(rules_data):
        idx = row.get('recheck_index')
        if idx is None:
            continue
        if idx < 0 or idx >= len(rules_data):
            raise InspectionError(f'第 {i + 1} 条规则的复检规则序号超出范围')
        edges[i] = idx

    # DFS 找环；自指（i→i）合法，表示复检沿用本规则重新抽样
    for start in edges:
        seen = []
        cursor = start
        while cursor in edges:
            nxt = edges[cursor]
            if nxt == cursor:
                break
            if nxt in seen:
                raise InspectionError('复检规则链不能形成循环')
            seen.append(nxt)
            cursor = nxt


def _save_rules(plan, rules_data):
    """落库规则并建立复检规则链接（外键需先有主键，故先批量创建再批量更新）"""
    rules = [
        SamplingRule(
            plan=plan,
            severity=row['severity'],
            batch_min=row['batch_min'],
            batch_max=row.get('batch_max', 0),
            sample_ratio=row.get('sample_ratio'),
            fixed_sample_count=row.get('fixed_sample_count'),
            min_sample_count=row.get('min_sample_count', 1),
            rounding_rule=row['rounding_rule'],
            priority=PRIORITY_TIGHTENED if row['severity'] == SEVERITY_TIGHTENED
            else PRIORITY_NORMAL,
        )
        for row in rules_data
    ]
    SamplingRule.objects.bulk_create(rules)

    _validate_recheck_index_graph(rules_data)
    to_update = []
    for i, row in enumerate(rules_data):
        idx = row.get('recheck_index')
        if idx is not None:
            rules[i].recheck_rule = rules[idx]
            to_update.append(rules[i])
    if to_update:
        SamplingRule.objects.bulk_update(to_update, ['recheck_rule'])
    return rules


@transaction.atomic
def create_draft(data, *, user=None):
    """创建方案草案（含规则、检查项）"""
    plan = InspectionPlan.objects.create(
        code=data['code'],
        name=data['name'],
        version=data.get('version', '1.0'),
        category_id=data['category'],
        source=data.get('source', ''),
        risk_level=data.get('risk_level', ''),
        accept_count=data['accept_count'],
        reject_count=data['reject_count'],
        remark=data.get('remark', ''),
        status=PLAN_DRAFT,
        created_by=user,
    )
    _save_rules(plan, data['rules'])
    InspectionItem.objects.bulk_create([
        InspectionItem(
            plan=plan,
            name=row['name'],
            method=row.get('method', ''),
            standard=row.get('standard', ''),
            is_critical=row.get('is_critical', False),
            sort_order=row.get('sort_order', 0),
        )
        for row in data['items']
    ])
    return plan


@transaction.atomic
def update_draft(plan, data):
    """整体更新草案（规则与检查项全量替换；发布后不可改）"""
    plan = InspectionPlan.objects.select_for_update().get(pk=plan.pk)
    if plan.status != PLAN_DRAFT:
        raise InspectionError('只有草案可以编辑，请创建新版本')

    # 先解除规则间复检引用，避免自引用外键级联删除冲突
    plan.rules.update(recheck_rule=None)
    plan.rules.all().delete()
    plan.items.all().delete()

    plan.code = data['code']
    plan.name = data['name']
    plan.version = data.get('version', plan.version)
    plan.category_id = data['category']
    plan.source = data.get('source', '')
    plan.risk_level = data.get('risk_level', '')
    plan.accept_count = data['accept_count']
    plan.reject_count = data['reject_count']
    plan.remark = data.get('remark', '')
    plan.save()

    _save_rules(plan, data['rules'])
    InspectionItem.objects.bulk_create([
        InspectionItem(
            plan=plan,
            name=row['name'],
            method=row.get('method', ''),
            standard=row.get('standard', ''),
            is_critical=row.get('is_critical', False),
            sort_order=row.get('sort_order', 0),
        )
        for row in data['items']
    ])
    return plan


# ==================== 方案发布 / 撤回（生效区间） ====================

def _intervals_overlap(start_a, end_a, start_b, end_b):
    """两端闭区间判断，None 表示开放端"""
    if end_a is not None and end_a <= start_b:
        return False
    if end_b is not None and end_b <= start_a:
        return False
    return True


def _scope_matches(plan, source, risk_level):
    """方案适用范围是否覆盖给定来源/风险（空值表示通用）"""
    if plan.source and source and plan.source != source:
        return False
    if plan.risk_level and risk_level and plan.risk_level != risk_level:
        return False
    return True


@transaction.atomic
def publish_plan(plan, *, effective_from=None, effective_to=None, user=None):
    """
    发布草案，写入生效区间：
    - 适用范围完全相同的旧已发布方案，在新版本生效时自动失效；
      若旧版本生效晚于新版本则拒绝，避免区间倒挂；
    - 精确度可比较（一方在来源、风险两个维度上都更具体或同等）的方案允许
      并存，匹配时取更精确者；
    - 精确度不可比较（如甲方只指定来源、乙方只指定风险等级，存在物资同时
      命中两者）一律拒绝，保证规则重叠得到一致处理。
    """
    plan = InspectionPlan.objects.select_for_update().get(pk=plan.pk)
    if plan.status != PLAN_DRAFT:
        raise InspectionError('只有草案可以发布')

    rules = list(plan.rules.all())
    if not rules:
        raise InspectionError('方案至少需要配置一条抽样规则')
    if not plan.items.exists():
        raise InspectionError('方案至少需要配置一个检查项')
    validate_rule_intervals(rules)

    now = timezone.now()
    effective_from = effective_from or now
    if effective_to is not None and effective_to <= effective_from:
        raise InspectionError('生效结束时间必须晚于开始时间')

    new_specificity = (bool(plan.source), bool(plan.risk_level))

    # 同品类下所有时间区间交叉的已发布方案
    active_qs = (
        InspectionPlan.objects
        .select_for_update()
        .filter(category_id=plan.category_id, status=PLAN_PUBLISHED)
        .exclude(pk=plan.pk)
    )
    for other in active_qs:
        if not _intervals_overlap(effective_from, effective_to,
                                  other.effective_from, other.effective_to):
            continue
        # 实际取值不重叠（指定了不同来源/不同风险等级）则互不影响
        if not _scope_matches(other, plan.source, plan.risk_level):
            continue

        old_specificity = (bool(other.source), bool(other.risk_level))
        if new_specificity == old_specificity:
            # 适用范围相同（取值已由 _scope_matches 确认一致）：新版本接替旧版本
            if other.effective_from >= effective_from:
                raise PlanOverlapError(
                    '已存在生效时间更晚的同范围方案，请调整生效开始时间'
                )
            other.effective_to = effective_from
            other.save(update_fields=['effective_to', 'updated_at'])
            continue

        # 精确度可比较（逐维一方都不输另一方）时允许并存，匹配取精确者
        new_more_specific = all(a >= b for a, b in zip(new_specificity, old_specificity))
        old_more_specific = all(a >= b for a, b in zip(old_specificity, new_specificity))
        if not (new_more_specific or old_more_specific):
            raise PlanOverlapError(
                '存在适用范围交叉但精确度不可比较的生效方案'
                '（一方限定来源、另一方限定风险等级），'
                '请先撤回相关方案或统一适用来源/风险等级'
            )

    plan.status = PLAN_PUBLISHED
    plan.effective_from = effective_from
    plan.effective_to = effective_to
    plan.published_at = now
    plan.published_by = user
    plan.save(update_fields=[
        'status', 'effective_from', 'effective_to', 'published_at',
        'published_by', 'updated_at',
    ])
    return plan


@transaction.atomic
def withdraw_plan(plan, *, reason='', user=None, withdrawn_at=None):
    """撤回方案：立即终止生效区间，既有快照不受影响"""
    plan = InspectionPlan.objects.select_for_update().get(pk=plan.pk)
    if plan.status != PLAN_PUBLISHED:
        raise InspectionError('只有已发布方案可以撤回')
    now = withdrawn_at or timezone.now()
    if now < plan.effective_from:
        # 尚未到生效时间即撤回：生效区间置为空区间，不产生倒挂
        plan.effective_to = plan.effective_from
    elif plan.effective_to is None or plan.effective_to > now:
        plan.effective_to = now
    plan.status = PLAN_WITHDRAWN
    plan.withdrawn_at = now
    plan.withdraw_reason = reason
    plan.save(update_fields=[
        'status', 'effective_to', 'withdrawn_at', 'withdraw_reason', 'updated_at',
    ])
    return plan


def find_effective_plan(category_id, source, risk_level='', at=None):
    """
    查找某时刻对给定品类/来源/风险生效的方案。
    精确度排序：指定来源 > 全部来源，指定风险 > 全部风险。
    """
    at = at or timezone.now()
    source = source or ''
    risk_level = risk_level or ''
    qs = (
        InspectionPlan.objects
        .filter(category_id=category_id, status=PLAN_PUBLISHED)
        .filter(effective_from__lte=at)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=at))
        .filter(Q(source='') | Q(source=source))
        .filter(Q(risk_level='') | Q(risk_level=risk_level))
        .annotate(
            source_rank=Case(
                When(source=source, then=0),
                default=1, output_field=IntegerField(),
            ),
            risk_rank=Case(
                When(risk_level=risk_level, then=0),
                default=1, output_field=IntegerField(),
            ),
        )
        .order_by('source_rank', 'risk_rank', '-published_at', '-id')
    )
    plans = list(qs[:2])
    if not plans:
        return None
    best = plans[0]
    if len(plans) > 1:
        second = plans[1]
        # 同精确度（来源、风险两个维度的 rank 都相同）即存在无法取舍的重叠方案
        if (best.source_rank, best.risk_rank) == (second.source_rank, second.risk_rank):
            raise PlanOverlapError(
                f'品类 {category_id} 在 {at:%Y-%m-%d %H:%M} 存在多个同等适用范围的生效方案'
            )
    return best


# ==================== 快照固定 ====================

def _freeze_rule_detail(rule):
    """把命中规则（含复检规则）的全文固化为 JSON，供举证与复检沿用"""
    detail = {
        'rule_id': rule.id,
        'severity': rule.severity,
        'batch_min': rule.batch_min,
        'batch_max': rule.batch_max,
        'sample_ratio': str(rule.sample_ratio) if rule.sample_ratio else None,
        'fixed_sample_count': rule.fixed_sample_count,
        'min_sample_count': rule.min_sample_count,
        'rounding_rule': rule.rounding_rule,
        'priority': rule.priority,
    }
    if rule.recheck_rule_id:
        rc = rule.recheck_rule
        detail['recheck_rule'] = {
            'rule_id': rc.id,
            'severity': rc.severity,
            'batch_min': rc.batch_min,
            'batch_max': rc.batch_max,
            'sample_ratio': str(rc.sample_ratio) if rc.sample_ratio else None,
            'fixed_sample_count': rc.fixed_sample_count,
            'min_sample_count': rc.min_sample_count,
            'rounding_rule': rc.rounding_rule,
        }
    return detail


def get_fixed_snapshot(goods, batch_no):
    """返回批次已固定的首检快照；未固定返回 None（旧批次查询永远走这里）"""
    return (
        InspectionSnapshot.objects
        .filter(goods=goods, batch_no=batch_no, recheck_of__isnull=True)
        .prefetch_related('items')
        .first()
    )


@transaction.atomic
def fix_snapshot(*, goods, batch_no, batch_quantity, source='', risk_level='',
                 severity='auto', user=None, at=None):
    """
    到场核验：按物资类别、来源、批量固定方案快照。
    幂等——同一批次只固定一次，重复调用返回既有快照，绝不重算套用新方案。
    severity: auto（风险上升自动加严）/ normal / tightened
    """
    batch_no = (batch_no or '').strip()
    if not batch_no:
        raise InspectionError('批次号不能为空')
    batch_quantity = int(batch_quantity)
    if batch_quantity <= 0:
        raise InspectionError('批量必须大于 0')
    if severity not in ('auto', SEVERITY_NORMAL, SEVERITY_TIGHTENED):
        raise InspectionError('严格度取值非法')

    # 行锁 + 唯一约束双重保证幂等（并发到场核验）
    existing = (
        InspectionSnapshot.objects
        .select_for_update()
        .filter(goods=goods, batch_no=batch_no, recheck_of__isnull=True)
        .first()
    )
    if existing:
        return existing, False

    at = at or timezone.now()
    plan = find_effective_plan(
        category_id=goods.variety.category_id,
        source=source, risk_level=risk_level, at=at,
    )
    if plan is None:
        raise NoEffectivePlanError('当前品类、来源在此时刻没有生效中的抽检方案')

    if severity == 'auto':
        risk = risk_level.strip()
        prefer_tightened = risk.lower() in ELEVATED_RISK_LEVELS or risk in ELEVATED_RISK_LEVELS
    else:
        prefer_tightened = severity == SEVERITY_TIGHTENED

    rule, used_severity = resolve_rule(plan, batch_quantity,
                                       prefer_tightened=prefer_tightened)
    sample_count = compute_sample_count(rule, batch_quantity)

    try:
        with transaction.atomic():
            snapshot = InspectionSnapshot.objects.create(
                plan=plan,
                goods=goods,
                batch_no=batch_no,
                category_name=goods.variety.category.name,
                source=source or '',
                risk_level=risk_level or '',
                batch_quantity=batch_quantity,
                plan_code=plan.code,
                plan_name=plan.name,
                plan_version=plan.version,
                severity=used_severity,
                sample_count=sample_count,
                rounding_rule=rule.rounding_rule,
                accept_count=plan.accept_count,
                reject_count=plan.reject_count,
                rule_detail=_freeze_rule_detail(rule),
                fixed_by=user,
            )
            SnapshotItem.objects.bulk_create([
                SnapshotItem(
                    snapshot=snapshot,
                    name=item.name,
                    method=item.method,
                    standard=item.standard,
                    is_critical=item.is_critical,
                    sort_order=item.sort_order,
                )
                for item in plan.items.all()
            ])
    except IntegrityError:
        # 并发到场核验：另一事务已固定同批次，返回既有快照，不重算
        existing = (
            InspectionSnapshot.objects
            .prefetch_related('items')
            .get(goods=goods, batch_no=batch_no, recheck_of__isnull=True)
        )
        return existing, False
    return snapshot, True


# ==================== 判定 ====================

@transaction.atomic
def judge_snapshot(snapshot, item_results, *, user=None, remark=''):
    """
    录入逐项检验结果并统一判定。
    item_results: [{item_id, checked_count, defect_count}, ...]
    - 关键项任一不合格直接判不合格；
    - 总不合格数 <= Ac 合格，>= Re 不合格，介于其间让步接收；
    - 已判定快照不可改判（保证证据一致，复检须另走加严复检）。
    """
    snapshot = InspectionSnapshot.objects.select_for_update().get(pk=snapshot.pk)
    if snapshot.result != RESULT_PENDING:
        raise InspectionError('该批次已判定，不能重复判定；如需复检请发起加严复检')

    items = {item.pk: item for item in snapshot.items.all()}
    if not item_results:
        raise InspectionError('请录入检验结果')

    total_defects = 0
    critical_failed = False
    touched = set()
    for row in item_results:
        item = items.get(row.get('item_id'))
        if item is None:
            raise InspectionError('检查项不属于该快照')
        touched.add(item.pk)
        checked = int(row.get('checked_count', 0))
        defects = int(row.get('defect_count', 0))
        if checked < 0 or defects < 0:
            raise InspectionError('检验数量不能为负')
        if checked > snapshot.sample_count:
            raise InspectionError(f'检查项「{item.name}」已检数量超过样本数量 {snapshot.sample_count}')
        if defects > checked:
            raise InspectionError(f'检查项「{item.name}」不合格数量不能超过已检数量')
        item.checked_count = checked
        item.defect_count = defects
        item.item_result = RESULT_PASS if defects == 0 else RESULT_FAIL
        item.save(update_fields=['checked_count', 'defect_count', 'item_result'])
        total_defects += defects
        if item.is_critical and defects > 0:
            critical_failed = True

    if len(touched) != len(items):
        raise InspectionError('存在未录入结果的检查项')

    if critical_failed:
        result = RESULT_FAIL
    elif total_defects <= snapshot.accept_count:
        result = RESULT_PASS
    elif total_defects >= snapshot.reject_count:
        result = RESULT_FAIL
    else:
        result = RESULT_CONDITIONAL

    snapshot.result = result
    snapshot.judged_at = timezone.now()
    snapshot.judged_by = user
    snapshot.judge_remark = remark
    snapshot.save(update_fields=['result', 'judged_at', 'judged_by', 'judge_remark'])
    return snapshot


# ==================== 加严复检 ====================

@transaction.atomic
def start_recheck(snapshot, *, user=None, at=None):
    """
    不合格后发起加严复检：沿用批次固定时的原方案（不套用新方案），
    用命中规则上配置的复检规则重新抽样，生成独立复检快照。
    幂等：同一首检快照只允许一个复检快照。
    """
    snapshot = InspectionSnapshot.objects.select_for_update().get(pk=snapshot.pk)
    if snapshot.recheck_of_id is not None:
        raise InspectionError('复检快照不能再次复检')
    if snapshot.result != RESULT_FAIL:
        raise InspectionError('只有判定不合格的批次可以发起加严复检')

    existing = InspectionSnapshot.objects.filter(recheck_of=snapshot).first()
    if existing:
        return existing, False

    frozen_recheck = snapshot.rule_detail.get('recheck_rule')
    if frozen_recheck:
        # 优先使用固定时声明的复检规则，方案日后调整不影响复检
        sample_count = _compute_frozen_sample_count(
            frozen_recheck, snapshot.batch_quantity)
        recheck_severity = frozen_recheck['severity']
        rounding = frozen_recheck['rounding_rule']
        frozen = frozen_recheck
    else:
        # 未单独配置复检规则：在原方案版本（已发布方案内容不可变，撤回也不改规则）
        # 中取覆盖该批量的加严规则；连加严规则也没有时，沿用快照自身的冻结规则
        try:
            rule, recheck_severity = resolve_rule(
                snapshot.plan, snapshot.batch_quantity, prefer_tightened=True)
            sample_count = compute_sample_count(rule, snapshot.batch_quantity)
            rounding = rule.rounding_rule
            frozen = _freeze_rule_detail(rule)
        except InspectionError:
            own = snapshot.rule_detail
            sample_count = _compute_frozen_sample_count(
                own, snapshot.batch_quantity)
            recheck_severity = own['severity']
            rounding = own['rounding_rule']
            frozen = own

    try:
        with transaction.atomic():
            recheck = InspectionSnapshot.objects.create(
                plan=snapshot.plan,
                goods=snapshot.goods,
                batch_no=snapshot.batch_no,
                category_name=snapshot.category_name,
                source=snapshot.source,
                risk_level=snapshot.risk_level,
                batch_quantity=snapshot.batch_quantity,
                plan_code=snapshot.plan_code,
                plan_name=snapshot.plan_name,
                plan_version=snapshot.plan_version,
                severity=recheck_severity,
                sample_count=sample_count,
                rounding_rule=rounding,
                accept_count=snapshot.accept_count,
                reject_count=snapshot.reject_count,
                rule_detail=frozen,
                fixed_by=user,
                recheck_of=snapshot,
            )
            SnapshotItem.objects.bulk_create([
                SnapshotItem(
                    snapshot=recheck,
                    name=item.name,
                    method=item.method,
                    standard=item.standard,
                    is_critical=item.is_critical,
                    sort_order=item.sort_order,
                )
                for item in snapshot.items.all()
            ])
    except IntegrityError:
        # 并发复检：另一事务已生成复检快照，返回既有的
        existing = InspectionSnapshot.objects.prefetch_related('items').get(
            recheck_of=snapshot)
        return existing, False
    return recheck, True


def _compute_frozen_sample_count(frozen, batch_quantity):
    """按快照中固化的复检规则计算样本数（小批量取整规则保持一致）"""
    ratio = frozen.get('sample_ratio')
    fixed = frozen.get('fixed_sample_count')
    if ratio is None and fixed is None:
        raise InspectionError('固化的复检规则缺少抽样配置')
    if ratio is not None:
        ratio_count = round_sample_count(
            decimal.Decimal(ratio) * batch_quantity, frozen['rounding_rule'])
    else:
        ratio_count = None
    if fixed is not None and ratio_count is not None:
        count = max(fixed, ratio_count)
    else:
        count = fixed if fixed is not None else ratio_count
    count = max(count, frozen.get('min_sample_count', 1))
    return min(count, batch_quantity)
