"""
抽检管理URL配置
"""
from django.urls import path
from .views import (
    InspectionCompleteView, InspectionDetailView, InspectionFixView, InspectionListView,
    SamplingPlanDetailView, SamplingPlanListView, SamplingPlanPublishView,
    SamplingPlanWithdrawView,
)

urlpatterns = [
    # 抽检方案管理
    path('sampling-plans/', SamplingPlanListView.as_view(), name='sampling-plan-list'),
    path('sampling-plans/<int:pk>/', SamplingPlanDetailView.as_view(), name='sampling-plan-detail'),
    path('sampling-plans/<int:pk>/publish/', SamplingPlanPublishView.as_view(), name='sampling-plan-publish'),
    path('sampling-plans/<int:pk>/withdraw/', SamplingPlanWithdrawView.as_view(), name='sampling-plan-withdraw'),

    # 到场核验
    path('inspections/', InspectionListView.as_view(), name='inspection-list'),
    path('inspections/fix/', InspectionFixView.as_view(), name='inspection-fix'),
    path('inspections/<int:pk>/', InspectionDetailView.as_view(), name='inspection-detail'),
    path('inspections/<int:pk>/complete/', InspectionCompleteView.as_view(), name='inspection-complete'),
]
