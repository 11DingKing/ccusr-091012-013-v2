"""
库房管理过滤器 - 使用 django-filter
"""
import django_filters
from django.db.models import F
from .models import Unit, Category, Variety, Goods, StockIn, StockOut, Warning, Approval


class UnitFilter(django_filters.FilterSet):
    """单位过滤器"""
    name = django_filters.CharFilter(field_name='name', lookup_expr='icontains')
    is_active = django_filters.BooleanFilter(field_name='is_active')
    
    class Meta:
        model = Unit
        fields = ['name', 'is_active']


class CategoryFilter(django_filters.FilterSet):
    """品类过滤器"""
    name = django_filters.CharFilter(field_name='name', lookup_expr='icontains')
    is_active = django_filters.BooleanFilter(field_name='is_active')
    
    class Meta:
        model = Category
        fields = ['name', 'is_active']


class VarietyFilter(django_filters.FilterSet):
    """品种过滤器"""
    name = django_filters.CharFilter(field_name='name', lookup_expr='icontains')
    category_id = django_filters.NumberFilter(field_name='category_id')
    is_active = django_filters.BooleanFilter(field_name='is_active')
    
    class Meta:
        model = Variety
        fields = ['name', 'category_id', 'is_active']


class GoodsFilter(django_filters.FilterSet):
    """货物过滤器"""
    name = django_filters.CharFilter(field_name='name', lookup_expr='icontains')
    code = django_filters.CharFilter(field_name='code', lookup_expr='icontains')
    variety_id = django_filters.NumberFilter(field_name='variety_id')
    category_id = django_filters.NumberFilter(field_name='variety__category_id')
    is_warning = django_filters.BooleanFilter(method='filter_is_warning')
    
    class Meta:
        model = Goods
        fields = ['name', 'code', 'variety_id', 'category_id', 'is_warning']
    
    def filter_is_warning(self, queryset, name, value):
        if value:
            return queryset.filter(quantity__lte=F('warning_threshold'))
        return queryset


class StockInFilter(django_filters.FilterSet):
    """入库记录过滤器"""
    goods_id = django_filters.NumberFilter(field_name='goods_id')
    start_date = django_filters.DateFilter(field_name='stock_in_time', lookup_expr='date__gte')
    end_date = django_filters.DateFilter(field_name='stock_in_time', lookup_expr='date__lte')
    
    class Meta:
        model = StockIn
        fields = ['goods_id', 'start_date', 'end_date']


class StockOutFilter(django_filters.FilterSet):
    """出库记录过滤器"""
    goods_id = django_filters.NumberFilter(field_name='goods_id')
    status = django_filters.CharFilter(field_name='status')
    start_date = django_filters.DateFilter(field_name='created_at', lookup_expr='date__gte')
    end_date = django_filters.DateFilter(field_name='created_at', lookup_expr='date__lte')
    
    class Meta:
        model = StockOut
        fields = ['goods_id', 'status', 'start_date', 'end_date']


class WarningFilter(django_filters.FilterSet):
    """预警过滤器"""
    is_read = django_filters.BooleanFilter(field_name='is_read')
    type = django_filters.CharFilter(field_name='type')
    
    class Meta:
        model = Warning
        fields = ['is_read', 'type']


class ApprovalFilter(django_filters.FilterSet):
    """审批过滤器"""
    status = django_filters.CharFilter(field_name='status')
    
    class Meta:
        model = Approval
        fields = ['status']
