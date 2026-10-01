"""
报表URL配置
"""
from django.urls import path
from .views import DashboardView, DailyReportView, ExportView, SystemMonitorView

urlpatterns = [
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('daily-report/', DailyReportView.as_view(), name='daily-report'),
    path('export/', ExportView.as_view(), name='export'),
    path('system-monitor/', SystemMonitorView.as_view(), name='system-monitor'),
]
