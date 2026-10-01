"""
认证模块过滤器 - 使用 django-filter
"""
import django_filters
from .models import OperationLog


class OperationLogFilter(django_filters.FilterSet):
    """操作日志过滤器"""
    action = django_filters.CharFilter(field_name='action', lookup_expr='exact')
    module = django_filters.CharFilter(field_name='module', lookup_expr='icontains')
    start_date = django_filters.DateFilter(field_name='created_at', lookup_expr='date__gte')
    end_date = django_filters.DateFilter(field_name='created_at', lookup_expr='date__lte')
    user = django_filters.NumberFilter(field_name='user_id')
    
    class Meta:
        model = OperationLog
        fields = ['action', 'module', 'start_date', 'end_date', 'user']
