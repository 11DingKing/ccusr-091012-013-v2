"""
抽检管理序列化器
"""
from decimal import Decimal

from rest_framework import serializers

from apps.core.exceptions import BusinessException
from apps.warehouse.models import Category
from .models import Inspection, SamplingPlan
from .services import validate_plan_data


class SamplingPlanSerializer(serializers.ModelSerializer):
    """抽检方案序列化器"""
    category_name = serializers.CharField(source='category.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    published_by_name = serializers.CharField(source='published_by.username', read_only=True)
    withdrawn_by_name = serializers.CharField(source='withdrawn_by.username', read_only=True)

    class Meta:
        model = SamplingPlan
        fields = [
            'id', 'name', 'category', 'category_name', 'source',
            'min_quantity', 'max_quantity', 'sample_ratio', 'tightened_ratio',
            'min_sample_size', 'max_sample_size', 'check_items', 'priority',
            'status', 'status_display', 'effective_from', 'effective_to',
            'published_at', 'published_by', 'published_by_name',
            'withdrawn_at', 'withdrawn_by', 'withdrawn_by_name', 'withdraw_reason',
            'created_by', 'created_by_name', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class SamplingPlanCreateSerializer(serializers.Serializer):
    """抽检方案创建/更新序列化器"""
    name = serializers.CharField(min_length=1, max_length=50, required=True, error_messages={
        'required': '请输入方案名称',
        'blank': '方案名称不能为空',
        'max_length': '方案名称最多50个字',
    })
    category = serializers.IntegerField(required=True, error_messages={
        'required': '请选择物资品类',
    })
    source = serializers.CharField(max_length=100, required=False, allow_blank=True,
                                   default='', error_messages={
                                       'max_length': '适用来源最多100个字',
                                   })
    min_quantity = serializers.DecimalField(max_digits=12, decimal_places=2,
                                            required=False, default=Decimal('0'))
    max_quantity = serializers.DecimalField(max_digits=12, decimal_places=2,
                                            required=False, allow_null=True, default=None)
    sample_ratio = serializers.DecimalField(max_digits=5, decimal_places=4, required=True,
                                            error_messages={'required': '请输入抽检比例'})
    tightened_ratio = serializers.DecimalField(max_digits=5, decimal_places=4, required=True,
                                               error_messages={'required': '请输入加严抽检比例'})
    min_sample_size = serializers.IntegerField(required=False, default=1)
    max_sample_size = serializers.IntegerField(required=False, allow_null=True, default=None)
    check_items = serializers.ListField(child=serializers.DictField(), required=True,
                                        error_messages={'required': '请配置检查项'})
    priority = serializers.IntegerField(required=False, default=0)
    effective_from = serializers.DateTimeField(required=False, allow_null=True, default=None)
    effective_to = serializers.DateTimeField(required=False, allow_null=True, default=None)

    def validate_category(self, value):
        if not Category.objects.filter(pk=value).exists():
            raise serializers.ValidationError('物资品类不存在')
        return value

    def validate(self, data):
        try:
            validate_plan_data(data)
        except BusinessException as exc:
            raise serializers.ValidationError(exc.message)
        return data


class InspectionSerializer(serializers.ModelSerializer):
    """到场核验序列化器"""
    category_name = serializers.CharField(source='category.name', read_only=True)
    plan_name = serializers.CharField(source='plan.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    inspection_level_display = serializers.CharField(source='get_inspection_level_display',
                                                     read_only=True)
    conclusion_display = serializers.CharField(source='get_conclusion_display', read_only=True)
    verified_by_name = serializers.CharField(source='verified_by.username', read_only=True)

    class Meta:
        model = Inspection
        fields = [
            'id', 'batch_no', 'category', 'category_name', 'source', 'batch_quantity',
            'plan', 'plan_name', 'plan_snapshot', 'inspection_level',
            'inspection_level_display', 'tightened_trigger',
            'sample_size', 'check_items', 'item_results',
            'status', 'status_display', 'conclusion', 'conclusion_display',
            'verified_by', 'verified_by_name', 'verified_at', 'completed_at',
            'remark', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class InspectionFixSerializer(serializers.Serializer):
    """到场核验固定快照序列化器"""
    batch_no = serializers.CharField(min_length=1, max_length=50, required=True,
                                     error_messages={
                                         'required': '请输入批次号',
                                         'blank': '批次号不能为空',
                                         'max_length': '批次号最多50个字',
                                     })
    category = serializers.IntegerField(required=True, error_messages={
        'required': '请选择物资品类',
    })
    source = serializers.CharField(max_length=100, required=False, allow_blank=True,
                                   default='', error_messages={
                                       'max_length': '批次来源最多100个字',
                                   })
    batch_quantity = serializers.DecimalField(max_digits=12, decimal_places=2, required=True,
                                              error_messages={'required': '请输入批量'})
    verified_at = serializers.DateTimeField(required=False, allow_null=True, default=None)

    def validate_category(self, value):
        if not Category.objects.filter(pk=value).exists():
            raise serializers.ValidationError('物资品类不存在')
        return value

    def validate_batch_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError('批量必须大于0')
        return value


class InspectionCompleteSerializer(serializers.Serializer):
    """核验判定序列化器"""
    item_results = serializers.ListField(child=serializers.DictField(), required=True,
                                         error_messages={'required': '请录入检查项结果'})
    remark = serializers.CharField(required=False, allow_blank=True, default='')
