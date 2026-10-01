"""
人员管理URL配置
"""
from django.urls import path
from .views import (
    StockOutPersonListView, StockOutPersonDetailView, AdminUserListView
)

urlpatterns = [
    path('stock-out-persons/', StockOutPersonListView.as_view(), name='stock-out-person-list'),
    path('stock-out-persons/<int:pk>/', StockOutPersonDetailView.as_view(), name='stock-out-person-detail'),
    path('admin-users/', AdminUserListView.as_view(), name='admin-user-list'),
]
