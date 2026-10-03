"""
抽检业务规则

集中维护抽检方案与到场核验的一致性规则：
- 方案数据校验（发布前必须满足）
- 样本量计算（小批量统一向上取整并受上下限约束）
- 方案匹配（规则重叠时按确定性顺序取舍）
- 快照固定（幂等，同批次号不重复套用方案）
- 加严复检（同品类同来源上次判定不合格时自动加严）
- 判定录入（检查项结果齐全，结论由结果推导）
"""
from decimal import Decimal, ROUND_CEILING

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.exceptions import BusinessException
from .models import Inspection, SamplingPlan

# 样本量取整方式：向上取整，保证小批量抽检比例不打折扣
ROUNDING_MODE = 'ceil'


def validate_plan_data(data):
    """校验方案数据，data 为包含方案字段的字典，校验失败抛出 BusinessException"""
    sample_ratio = data.get('sample_ratio')
    tightened_ratio = data.get('tightened_ratio')
    if sample_ratio is not None and not (Decimal('0') < sample_ratio <= Decimal('1')):
        raise BusinessException('抽检比例必须在0到1之间')
    if tightened_ratio is not None and not (Decimal('0') < tightened_ratio <= Decimal('1')):
        raise BusinessException('加严抽检比例必须在0到1之间')
    if (sample_ratio is not None and tightened_ratio is not None
            and tightened_ratio < sample_ratio):
        raise BusinessException('加严抽检比例不能低于抽检比例')

    min_quantity = data.get('min_quantity')
    max_quantity = data.get('max_quantity')
    if min_quantity is not None and min_quantity < 0:
        raise BusinessException('批量下限不能为负数')
    if (min_quantity is not None and max_quantity is not None
            and max_quantity <= min_quantity):
        raise BusinessException('批量上限必须大于批量下限')

    min_sample_size = data.get('min_sample_size')
    max_sample_size = data.get('max_sample_size')
    if min_sample_size is not None and min_sample_size < 1:
        raise BusinessException('最小样本数至少为1')
    if (min_sample_size is not None and max_sample_size is not None
            and max_sample_size < min_sample_size):
        raise BusinessException('最大样本数不能小于最小样本数')

    effective_from = data.get('effective_from')
    effective_to = data.get('effective_to')
    if effective_from and effective_to and effective_to <= effective_from:
        raise BusinessException('生效截止时间必须晚于生效开始时间')

    check_items = data.get('check_items')
    if check_items is not None:
        validate_check_items(check_items)


def validate_check_items(check_items):
    """校验检查项格式：非空列表，每项必须有不重复的名称"""
    if not isinstance(check_items, list) or not check_items:
        raise BusinessException('检查项不能为空')
    names = []
    for item in check_items:
        if not isinstance(item, dict) or not str(item.get('name', '')).strip():
            raise BusinessException('每个检查项必须包含名称')
        names.append(str(item['name']).strip())
    if len(names) != len(set(names)):
        raise BusinessException('检查项名称不能重复')


def check_plan_publishable(plan):
    """发布前校验方案当前数据是否满足全部规则"""
    validate_plan_data({
        'sample_ratio': plan.sample_ratio,
        'tightened_ratio': plan.tightened_ratio,
        'min_quantity': plan.min_quantity,
        'max_quantity': plan.max_quantity,
        'min_sample_size': plan.min_sample_size,
        'max_sample_size': plan.max_sample_size,
        'effective_from': plan.effective_from,
        'effective_to': plan.effective_to,
        'check_items': plan.check_items,
    })


def compute_sample_size(batch_quantity, ratio, min_sample_size, max_sample_size):
    """计算样本数量

    统一规则：批量 × 比例向上取整，再套用最小/最大样本数，
    且样本数量不超过批量向上取整后的单位数，至少为1。
    """
    units = int(batch_quantity.to_integral_value(rounding=ROUND_CEILING))
    size = int((batch_quantity * ratio).to_integral_value(rounding=ROUND_CEILING))
    size = max(size, min_sample_size)
    if max_sample_size is not None:
        size = min(size, max_sample_size)
    size = min(size, units)
    return max(size, 1)


def _quantity_span(plan):
    """批量区间跨度，上限留空视为无穷大（排序时排在后面）"""
    if plan.max_quantity is None:
        return None
    return plan.max_quantity - plan.min_quantity


def resolve_plan(category_id, source, quantity, moment):
    """匹配指定品类、来源、批量和时刻适用的已发布方案

    规则重叠时按确定性顺序取舍：优先级高者优先；仍并列时来源精确
    匹配优先于通用（留空）方案；再并列时批量区间跨度小者优先；
    最后按创建先后（id 升序）取舍，保证结果可重现。
    """
    candidates = [
        plan for plan in SamplingPlan.objects.filter(
            status='published', category_id=category_id,
        )
        if plan.matches(source, quantity, moment)
    ]
    if not candidates:
        return None

    def sort_key(plan):
        span = _quantity_span(plan)
        return (
            -plan.priority,
            0 if plan.source else 1,
            span is None,
            span if span is not None else Decimal('0'),
            plan.id,
        )

    candidates.sort(key=sort_key)
    return candidates[0]


def find_tightened_trigger(category_id, source, before=None):
    """查找加严触发记录：同品类同来源最近一次已判定核验为不合格时返回该记录"""
    queryset = Inspection.objects.filter(
        category_id=category_id, source=source, status='completed',
    )
    if before is not None:
        queryset = queryset.filter(completed_at__lte=before)
    latest = queryset.order_by('-completed_at', '-id').first()
    if latest and latest.conclusion == 'unqualified':
        return latest
    return None


def build_plan_snapshot(plan, inspection_level, applied_ratio):
    """冻结方案内容，快照生成后与方案后续变更无关"""
    return {
        'plan_id': plan.id,
        'plan_name': plan.name,
        'source': plan.source,
        'priority': plan.priority,
        'min_quantity': str(plan.min_quantity),
        'max_quantity': str(plan.max_quantity) if plan.max_quantity is not None else None,
        'sample_ratio': str(plan.sample_ratio),
        'tightened_ratio': str(plan.tightened_ratio),
        'applied_ratio': str(applied_ratio),
        'inspection_level': inspection_level,
        'min_sample_size': plan.min_sample_size,
        'max_sample_size': plan.max_sample_size,
        'rounding': ROUNDING_MODE,
        'check_items': plan.check_items,
        'effective_from': plan.effective_from.isoformat() if plan.effective_from else None,
        'effective_to': plan.effective_to.isoformat() if plan.effective_to else None,
        'published_at': plan.published_at.isoformat() if plan.published_at else None,
    }


@transaction.atomic
def fix_inspection(batch_no, category, source, batch_quantity, verified_by, verified_at=None):
    """到场核验固定方案快照

    同一批次号重复核验时直接返回原快照（幂等），不重新匹配方案；
    批次号已存在但批次信息不一致时拒绝，防止批次号误用。
    """
    existing = Inspection.objects.filter(batch_no=batch_no).first()
    if existing:
        return _reuse_existing(existing, category, source, batch_quantity), False

    moment = verified_at or timezone.now()
    plan = resolve_plan(category.id, source, batch_quantity, moment)
    if plan is None:
        raise BusinessException('没有适用于该批次的已发布抽检方案')

    trigger = find_tightened_trigger(category.id, source, before=moment)
    if trigger:
        inspection_level = 'tightened'
        applied_ratio = plan.tightened_ratio
    else:
        inspection_level = 'normal'
        applied_ratio = plan.sample_ratio

    sample_size = compute_sample_size(
        batch_quantity, applied_ratio, plan.min_sample_size, plan.max_sample_size,
    )

    try:
        with transaction.atomic():
            inspection = Inspection.objects.create(
                batch_no=batch_no,
                category=category,
                source=source,
                batch_quantity=batch_quantity,
                plan=plan,
                plan_snapshot=build_plan_snapshot(plan, inspection_level, applied_ratio),
                inspection_level=inspection_level,
                tightened_trigger=trigger,
                sample_size=sample_size,
                check_items=plan.check_items,
                verified_by=verified_by,
                verified_at=moment,
            )
    except IntegrityError:
        # 并发下批次号已被其他请求固定，返回先到的快照
        existing = Inspection.objects.get(batch_no=batch_no)
        return _reuse_existing(existing, category, source, batch_quantity), False
    return inspection, True


def _reuse_existing(existing, category, source, batch_quantity):
    """复用已固定快照前校验批次信息一致"""
    if (existing.category_id != category.id
            or existing.source != source
            or existing.batch_quantity != batch_quantity):
        raise BusinessException('批次号已存在且批次信息不一致')
    return existing


def complete_inspection(inspection, item_results, remark=''):
    """录入检查项结果并判定

    检查项结果必须逐项覆盖快照中的检查项，结论由结果推导：
    全部通过为合格，任一不通过为不合格，保证判定与依据一致。
    """
    if inspection.status == 'completed':
        raise BusinessException('该核验已完成判定，不能重复录入')

    validate_item_results(item_results)
    expected = {str(item['name']).strip() for item in inspection.check_items}
    provided = {str(item['name']).strip() for item in item_results}
    if provided != expected:
        missing = '、'.join(sorted(expected - provided))
        extra = '、'.join(sorted(provided - expected))
        parts = []
        if missing:
            parts.append(f'缺少检查项：{missing}')
        if extra:
            parts.append(f'多余检查项：{extra}')
        raise BusinessException('检查项结果与方案快照不一致（' + '；'.join(parts) + '）')

    all_passed = all(item['result'] == 'pass' for item in item_results)
    inspection.item_results = item_results
    inspection.conclusion = 'qualified' if all_passed else 'unqualified'
    inspection.status = 'completed'
    inspection.completed_at = timezone.now()
    if remark:
        inspection.remark = remark
    inspection.save()
    return inspection


def validate_item_results(item_results):
    """校验检查项结果格式"""
    if not isinstance(item_results, list) or not item_results:
        raise BusinessException('检查项结果不能为空')
    names = []
    for item in item_results:
        if not isinstance(item, dict) or not str(item.get('name', '')).strip():
            raise BusinessException('每条结果必须包含检查项名称')
        if item.get('result') not in ('pass', 'fail'):
            raise BusinessException('检查结果必须为pass或fail')
        names.append(str(item['name']).strip())
    if len(names) != len(set(names)):
        raise BusinessException('同一检查项不能重复录入结果')
