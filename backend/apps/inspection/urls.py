"""
抽检方案管理 URL 配置
"""
from django.urls import path
from .views import (
    PlanListView, PlanDetailView, PlanPublishView, PlanWithdrawView,
    SnapshotFixView, SnapshotListView, SnapshotDetailView,
    BatchSnapshotView, SnapshotJudgeView, SnapshotRecheckView,
)

urlpatterns = [
    # 抽检方案：草案 / 发布 / 撤回
    path('inspection/plans/', PlanListView.as_view(), name='inspection-plan-list'),
    path('inspection/plans/<int:pk>/', PlanDetailView.as_view(),
         name='inspection-plan-detail'),
    path('inspection/plans/<int:pk>/publish/', PlanPublishView.as_view(),
         name='inspection-plan-publish'),
    path('inspection/plans/<int:pk>/withdraw/', PlanWithdrawView.as_view(),
         name='inspection-plan-withdraw'),

    # 到场核验：固定快照、批次查询、判定、加严复检
    path('inspection/snapshots/fix/', SnapshotFixView.as_view(),
         name='inspection-snapshot-fix'),
    path('inspection/snapshots/batch/', BatchSnapshotView.as_view(),
         name='inspection-snapshot-batch'),
    path('inspection/snapshots/', SnapshotListView.as_view(),
         name='inspection-snapshot-list'),
    path('inspection/snapshots/<int:pk>/', SnapshotDetailView.as_view(),
         name='inspection-snapshot-detail'),
    path('inspection/snapshots/<int:pk>/judge/', SnapshotJudgeView.as_view(),
         name='inspection-snapshot-judge'),
    path('inspection/snapshots/<int:pk>/recheck/', SnapshotRecheckView.as_view(),
         name='inspection-snapshot-recheck'),
]
