"""
抽检方案管理序列化器
"""
import decimal

from rest_framework import serializers

from .models import (
    InspectionPlan, SamplingRule, InspectionItem,
    InspectionSnapshot, SnapshotItem,
    SEVERITY_NORMAL, SEVERITY_TIGHTENED,
    ROUND_UP, ROUND_HALF_UP, ROUND_DOWN,
)
from apps.warehouse.models import Category


class SamplingRuleSerializer(serializers.ModelSerializer):
    """抽样规则序列化器"""
    severity_display = serializers.CharField(source='get_severity_display', read_only=True)
    rounding_rule_display = serializers.CharField(source='get_rounding_rule_display', read_only=True)
    recheck_rule_id = serializers.IntegerField(source='recheck_rule.id', read_only=True)

    class Meta:
        model = SamplingRule
        fields = [
            'id', 'severity', 'severity_display',
            'batch_min', 'batch_max',
            'sample_ratio', 'fixed_sample_count', 'min_sample_count',
            'rounding_rule', 'rounding_rule_display', 'priority',
            'recheck_rule', 'recheck_rule_id', 'created_at',
        ]
        read_only_fields = ['id', 'priority', 'created_at']


class SamplingRuleWriteSerializer(serializers.Serializer):
    """抽样规则写入序列化器（方案草案内嵌套提交）"""
    id = serializers.IntegerField(required=False)
    severity = serializers.ChoiceField(
        choices=[SEVERITY_NORMAL, SEVERITY_TIGHTENED], default=SEVERITY_NORMAL)
    batch_min = serializers.IntegerField(min_value=1)
    batch_max = serializers.IntegerField(min_value=0, default=0)
    sample_ratio = serializers.DecimalField(
        max_digits=6, decimal_places=4, min_value=decimal.Decimal('0'),
        max_value=decimal.Decimal('1'), required=False, allow_null=True)
    fixed_sample_count = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    min_sample_count = serializers.IntegerField(min_value=1, default=1)
    rounding_rule = serializers.ChoiceField(
        choices=[ROUND_UP, ROUND_HALF_UP, ROUND_DOWN], default=ROUND_UP)
    # 复检规则在本次提交规则列表中的序号（0 基），草案保存时解析为具体规则
    recheck_index = serializers.IntegerField(min_value=0, required=False, allow_null=True)

    def validate(self, data):
        batch_min = data['batch_min']
        batch_max = data.get('batch_max', 0)
        if batch_max and batch_max < batch_min:
            raise serializers.ValidationError('批量上限不能小于下限')
        if not data.get('sample_ratio') and not data.get('fixed_sample_count'):
            raise serializers.ValidationError('抽样比例和固定样本数量至少配置一项')
        return data


class InspectionItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InspectionItem
        fields = ['id', 'name', 'method', 'standard', 'is_critical', 'sort_order']
        read_only_fields = ['id']


class InspectionItemWriteSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    name = serializers.CharField(max_length=100)
    method = serializers.CharField(max_length=200, allow_blank=True, default='')
    standard = serializers.CharField(max_length=200, allow_blank=True, default='')
    is_critical = serializers.BooleanField(default=False)
    sort_order = serializers.IntegerField(min_value=0, default=0)


class InspectionPlanListSerializer(serializers.ModelSerializer):
    """方案列表序列化器"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    published_by_name = serializers.CharField(source='published_by.username', read_only=True)
    is_editable = serializers.BooleanField(read_only=True)

    class Meta:
        model = InspectionPlan
        fields = [
            'id', 'code', 'name', 'version',
            'category', 'category_name', 'source', 'risk_level',
            'accept_count', 'reject_count',
            'status', 'status_display', 'is_editable',
            'effective_from', 'effective_to',
            'published_at', 'withdrawn_at', 'withdraw_reason',
            'created_by', 'created_by_name', 'published_by_name',
            'created_at', 'updated_at',
        ]


class InspectionPlanDetailSerializer(InspectionPlanListSerializer):
    """方案详情：含全部规则与检查项（草案编辑回显用）"""
    rules = SamplingRuleSerializer(many=True, read_only=True)
    items = InspectionItemSerializer(many=True, read_only=True)

    class Meta(InspectionPlanListSerializer.Meta):
        fields = InspectionPlanListSerializer.Meta.fields + ['rules', 'items', 'remark']


class InspectionPlanWriteSerializer(serializers.Serializer):
    """方案草案创建/更新序列化器"""
    code = serializers.CharField(max_length=50)
    name = serializers.CharField(max_length=200)
    version = serializers.CharField(max_length=20, default='1.0')
    category = serializers.IntegerField()
    source = serializers.CharField(max_length=100, allow_blank=True, default='')
    risk_level = serializers.CharField(max_length=20, allow_blank=True, default='')
    accept_count = serializers.IntegerField(min_value=0, default=0)
    reject_count = serializers.IntegerField(min_value=1, default=1)
    remark = serializers.CharField(allow_blank=True, default='')
    rules = SamplingRuleWriteSerializer(many=True)
    items = InspectionItemWriteSerializer(many=True)

    def validate_code(self, value):
        instance = self.context.get('instance')
        qs = InspectionPlan.objects.filter(code=value)
        if instance:
            qs = qs.exclude(pk=instance.pk)
        if qs.exists():
            raise serializers.ValidationError('方案编号已存在')
        return value

    def validate_category(self, value):
        if not Category.objects.filter(pk=value).exists():
            raise serializers.ValidationError('品类不存在')
        return value

    def validate(self, data):
        if data['reject_count'] <= data['accept_count']:
            raise serializers.ValidationError('不合格判定数 Re 必须大于合格判定数 Ac')
        if not data.get('rules'):
            raise serializers.ValidationError({'rules': '至少配置一条抽样规则'})
        if not data.get('items'):
            raise serializers.ValidationError({'items': '至少配置一个检查项'})
        return data


class PlanPublishSerializer(serializers.Serializer):
    """发布参数：生效区间"""
    effective_from = serializers.DateTimeField(required=False, allow_null=True)
    effective_to = serializers.DateTimeField(required=False, allow_null=True)

    def validate(self, data):
        start = data.get('effective_from')
        end = data.get('effective_to')
        if start and end and end <= start:
            raise serializers.ValidationError('生效结束时间必须晚于开始时间')
        return data


class PlanWithdrawSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200, allow_blank=True, default='')


# ==================== 快照 ====================

class SnapshotItemSerializer(serializers.ModelSerializer):
    item_result_display = serializers.CharField(source='get_item_result_display', read_only=True)

    class Meta:
        model = SnapshotItem
        fields = [
            'id', 'name', 'method', 'standard', 'is_critical', 'sort_order',
            'checked_count', 'defect_count', 'item_result', 'item_result_display',
        ]


class InspectionSnapshotSerializer(serializers.ModelSerializer):
    result_display = serializers.CharField(source='get_result_display', read_only=True)
    severity_display = serializers.CharField(source='get_severity_display', read_only=True)
    rounding_rule_display = serializers.CharField(source='get_rounding_rule_display', read_only=True)
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    fixed_by_name = serializers.CharField(source='fixed_by.username', read_only=True)
    judged_by_name = serializers.CharField(source='judged_by.username', read_only=True)
    items = SnapshotItemSerializer(many=True, read_only=True)
    recheck_count = serializers.IntegerField(source='rechecks.count', read_only=True)

    class Meta:
        model = InspectionSnapshot
        fields = [
            'id', 'plan', 'goods', 'goods_name', 'batch_no',
            'category_name', 'source', 'risk_level', 'batch_quantity',
            'plan_code', 'plan_name', 'plan_version',
            'severity', 'severity_display',
            'sample_count', 'rounding_rule', 'rounding_rule_display',
            'accept_count', 'reject_count', 'rule_detail',
            'fixed_at', 'fixed_by', 'fixed_by_name',
            'result', 'result_display',
            'judged_at', 'judged_by', 'judged_by_name', 'judge_remark',
            'recheck_of', 'recheck_count', 'items',
        ]


class FixSnapshotSerializer(serializers.Serializer):
    """到场核验固定快照入参"""
    goods = serializers.IntegerField()
    batch_no = serializers.CharField(max_length=50)
    batch_quantity = serializers.IntegerField(min_value=1)
    source = serializers.CharField(max_length=100, allow_blank=True, default='')
    risk_level = serializers.CharField(max_length=20, allow_blank=True, default='')
    severity = serializers.ChoiceField(
        choices=[('auto', '自动（风险上升加严）'),
                 (SEVERITY_NORMAL, '正常'),
                 (SEVERITY_TIGHTENED, '加严')],
        default='auto',
    )


class JudgeItemInputSerializer(serializers.Serializer):
    item_id = serializers.IntegerField()
    checked_count = serializers.IntegerField(min_value=0)
    defect_count = serializers.IntegerField(min_value=0, default=0)


class JudgeSnapshotSerializer(serializers.Serializer):
    """判定入参：逐项已检/不合格数量"""
    items = JudgeItemInputSerializer(many=True)
    remark = serializers.CharField(max_length=500, allow_blank=True, default='')
