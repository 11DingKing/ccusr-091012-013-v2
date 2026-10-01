from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from apps.authentication.backends import generate_token
from apps.authentication.models import User
from apps.warehouse.models import Category, Goods, Unit, Variety, Warning
from .cron import check_stock_warning
from .models import DailyReport
from .views import DashboardView


class ReportTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("report-user", "testpass123", role="admin")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_token(self.user)}")
        unit = Unit.objects.create(name="件", created_by=self.user)
        category = Category.objects.create(name="监管器材", unit=unit, created_by=self.user)
        variety = Variety.objects.create(name="封存设备", category=category, created_by=self.user)
        self.goods = Goods.objects.create(
            variety=variety, name="封存终端", code="RPT-001", quantity=Decimal("2"), warning_threshold=Decimal("5")
        )

    def test_daily_report_model(self):
        report = DailyReport.objects.create(report_date=date(2026, 9, 30), in_count=2, in_total=4, out_count=1, out_total=1)
        self.assertEqual(report.in_count, 2)
        self.assertIn("2026-09-30", str(report))

    def test_dashboard_view_counts_warning_goods(self):
        request = APIRequestFactory().get("/api/dashboard/")
        force_authenticate(request, user=self.user)
        response = DashboardView.as_view()(request)
        response.render()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["warning_goods_count"], 1)

    def test_warning_job_is_idempotent_for_unread_warning(self):
        check_stock_warning()
        check_stock_warning()
        self.assertEqual(Warning.objects.filter(goods=self.goods, is_read=False).count(), 1)

    def test_daily_report_range(self):
        response = self.client.get("/api/daily-report/", {"start_date": "2026-09-29", "end_date": "2026-10-01"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 3)

    def test_invalid_export_type(self):
        response = self.client.get("/api/export/", {"type": "unknown"})
        self.assertEqual(response.status_code, 400)

    def test_system_monitor_shape(self):
        response = self.client.get("/api/system-monitor/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("cpu", response.json()["data"])
