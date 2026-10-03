"""
抽检管理测试

覆盖方案生命周期（草案/发布/生效区间/撤回）、到场核验快照固定、
样本量取整、加严复检、规则重叠取舍与历史批次一致性。
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.backends import generate_token
from apps.authentication.models import User
from apps.warehouse.models import Category, Unit
from .models import Inspection, SamplingPlan
from .services import compute_sample_size, resolve_plan

CHECK_ITEMS = [
    {'name': '外观', 'standard': '无破损'},
    {'name': '封存标识', 'standard': '清晰完整'},
]


def make_plan_data(category_id, **overrides):
    data = {
        'name': '常规抽检方案',
        'category': category_id,
        'source': '',
        'min_quantity': '0',
        'max_quantity': None,
        'sample_ratio': '0.1',
        'tightened_ratio': '0.2',
        'min_sample_size': 1,
        'max_sample_size': None,
        'check_items': CHECK_ITEMS,
        'priority': 0,
        'effective_from': None,
        'effective_to': None,
    }
    data.update(overrides)
    return data


class InspectionFixture(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("inspection-user", "testpass123", role="admin")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_token(self.user)}")
        self.unit = Unit.objects.create(name="件", created_by=self.user)
        self.category = Category.objects.create(name="受控器材", unit=self.unit, created_by=self.user)

    def create_plan(self, publish=True, **overrides):
        data = make_plan_data(self.category.id, **overrides)
        response = self.client.post("/api/sampling-plans/", data, format="json")
        self.assertEqual(response.status_code, 200, response.json())
        plan_id = response.json()["data"]["id"]
        if publish:
            published = self.client.post(f"/api/sampling-plans/{plan_id}/publish/")
            self.assertEqual(published.status_code, 200, published.json())
        return SamplingPlan.objects.get(pk=plan_id)

    def fix_batch(self, batch_no, quantity, source="", category_id=None, **extra):
        payload = {
            'batch_no': batch_no,
            'category': category_id or self.category.id,
            'source': source,
            'batch_quantity': str(quantity),
        }
        payload.update(extra)
        return self.client.post("/api/inspections/fix/", payload, format="json")

    def complete_batch(self, inspection_id, results=None, **extra):
        payload = {
            'item_results': results if results is not None else [
                {'name': '外观', 'result': 'pass'},
                {'name': '封存标识', 'result': 'pass'},
            ],
        }
        payload.update(extra)
        return self.client.post(f"/api/inspections/{inspection_id}/complete/", payload, format="json")


class SamplingPlanLifecycleTest(InspectionFixture):
    def test_draft_publish_withdraw_flow(self):
        plan = self.create_plan(publish=False)
        self.assertEqual(plan.status, 'draft')

        published = self.client.post(f"/api/sampling-plans/{plan.id}/publish/")
        self.assertEqual(published.status_code, 200)
        plan.refresh_from_db()
        self.assertEqual(plan.status, 'published')
        self.assertIsNotNone(plan.published_at)
        self.assertEqual(plan.published_by, self.user)

        withdrawn = self.client.post(
            f"/api/sampling-plans/{plan.id}/withdraw/", {'reason': '比例偏低'}, format="json"
        )
        self.assertEqual(withdrawn.status_code, 200)
        plan.refresh_from_db()
        self.assertEqual(plan.status, 'withdrawn')
        self.assertEqual(plan.withdraw_reason, '比例偏低')
        self.assertEqual(plan.withdrawn_by, self.user)

    def test_published_plan_is_readonly_and_undeletable(self):
        plan = self.create_plan()
        updated = self.client.put(
            f"/api/sampling-plans/{plan.id}/",
            make_plan_data(self.category.id, name='改名'), format="json",
        )
        deleted = self.client.delete(f"/api/sampling-plans/{plan.id}/")
        self.assertEqual(updated.status_code, 400)
        self.assertEqual(deleted.status_code, 400)
        self.assertTrue(SamplingPlan.objects.filter(pk=plan.id).exists())

    def test_withdrawn_plan_is_terminal(self):
        plan = self.create_plan()
        self.client.post(f"/api/sampling-plans/{plan.id}/withdraw/", {'reason': '调整'}, format="json")
        republished = self.client.post(f"/api/sampling-plans/{plan.id}/publish/")
        edited = self.client.put(
            f"/api/sampling-plans/{plan.id}/",
            make_plan_data(self.category.id), format="json",
        )
        deleted = self.client.delete(f"/api/sampling-plans/{plan.id}/")
        self.assertEqual(republished.status_code, 400)
        self.assertEqual(edited.status_code, 400)
        self.assertEqual(deleted.status_code, 400)

    def test_draft_can_be_edited_and_deleted(self):
        plan = self.create_plan(publish=False)
        updated = self.client.put(
            f"/api/sampling-plans/{plan.id}/",
            make_plan_data(self.category.id, name='修订草案'), format="json",
        )
        self.assertEqual(updated.status_code, 200)
        plan.refresh_from_db()
        self.assertEqual(plan.name, '修订草案')

        deleted = self.client.delete(f"/api/sampling-plans/{plan.id}/")
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(SamplingPlan.objects.filter(pk=plan.id).exists())

    def test_withdraw_requires_reason(self):
        plan = self.create_plan()
        response = self.client.post(f"/api/sampling-plans/{plan.id}/withdraw/", {}, format="json")
        self.assertEqual(response.status_code, 400)
        plan.refresh_from_db()
        self.assertEqual(plan.status, 'published')

    def test_publish_validation(self):
        # 加严比例低于正常比例
        bad = self.client.post(
            "/api/sampling-plans/",
            make_plan_data(self.category.id, sample_ratio='0.3', tightened_ratio='0.2'),
            format="json",
        )
        self.assertEqual(bad.status_code, 400)
        # 批量区间倒置
        bad = self.client.post(
            "/api/sampling-plans/",
            make_plan_data(self.category.id, min_quantity='100', max_quantity='50'),
            format="json",
        )
        self.assertEqual(bad.status_code, 400)
        # 生效区间倒置
        now = timezone.now()
        bad = self.client.post(
            "/api/sampling-plans/",
            make_plan_data(
                self.category.id,
                effective_from=now.isoformat(),
                effective_to=(now - timedelta(days=1)).isoformat(),
            ),
            format="json",
        )
        self.assertEqual(bad.status_code, 400)
        # 检查项为空
        bad = self.client.post(
            "/api/sampling-plans/", make_plan_data(self.category.id, check_items=[]), format="json"
        )
        self.assertEqual(bad.status_code, 400)
        # 检查项重名
        bad = self.client.post(
            "/api/sampling-plans/",
            make_plan_data(self.category.id, check_items=[{'name': '外观'}, {'name': '外观'}]),
            format="json",
        )
        self.assertEqual(bad.status_code, 400)
        # 样本上下限倒置
        bad = self.client.post(
            "/api/sampling-plans/",
            make_plan_data(self.category.id, min_sample_size=5, max_sample_size=3),
            format="json",
        )
        self.assertEqual(bad.status_code, 400)


class SampleSizeRuleTest(TestCase):
    """小批量取整与上下限的一致处理"""

    def test_ratio_rounds_up(self):
        # 21 × 0.1 = 2.1 → 3
        self.assertEqual(compute_sample_size(Decimal('21'), Decimal('0.1'), 1, None), 3)

    def test_small_batch_at_least_one(self):
        # 3 × 0.1 = 0.3 → 1
        self.assertEqual(compute_sample_size(Decimal('3'), Decimal('0.1'), 1, None), 1)

    def test_min_sample_size_applies(self):
        self.assertEqual(compute_sample_size(Decimal('10'), Decimal('0.1'), 5, None), 5)

    def test_max_sample_size_caps(self):
        self.assertEqual(compute_sample_size(Decimal('1000'), Decimal('0.5'), 1, 8), 8)

    def test_never_exceeds_batch(self):
        # 最小样本数也不能超过批量本身
        self.assertEqual(compute_sample_size(Decimal('2'), Decimal('1'), 5, None), 2)

    def test_fractional_quantity_rounds_units_up(self):
        # 2.5 个单位按 3 个单位对待
        self.assertEqual(compute_sample_size(Decimal('2.5'), Decimal('1'), 1, None), 3)


class PlanMatchingTest(InspectionFixture):
    """规则重叠时的确定性取舍"""

    def test_higher_priority_wins(self):
        self.create_plan(name='低优先级', priority=1, sample_ratio='0.1', tightened_ratio='0.2')
        self.create_plan(name='高优先级', priority=9, sample_ratio='0.5', tightened_ratio='0.6')
        response = self.fix_batch('B-PRI', 100)
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['plan_snapshot']['plan_name'], '高优先级')
        self.assertEqual(data['sample_size'], 50)

    def test_specific_source_beats_wildcard(self):
        self.create_plan(name='通用方案', source='', sample_ratio='0.1', tightened_ratio='0.2')
        self.create_plan(
            name='专源方案', source='甲供应商', sample_ratio='0.4', tightened_ratio='0.5'
        )
        response = self.fix_batch('B-SRC', 100, source='甲供应商')
        data = response.json()['data']
        self.assertEqual(data['plan_snapshot']['plan_name'], '专源方案')
        self.assertEqual(data['sample_size'], 40)

    def test_narrower_quantity_range_wins(self):
        self.create_plan(
            name='宽区间', min_quantity='0', max_quantity='1000',
            sample_ratio='0.1', tightened_ratio='0.2',
        )
        self.create_plan(
            name='窄区间', min_quantity='0', max_quantity='100',
            sample_ratio='0.3', tightened_ratio='0.4',
        )
        response = self.fix_batch('B-SPAN', 50)
        data = response.json()['data']
        self.assertEqual(data['plan_snapshot']['plan_name'], '窄区间')
        self.assertEqual(data['sample_size'], 15)

    def test_earlier_created_wins_when_fully_tied(self):
        first = self.create_plan(name='先建方案', sample_ratio='0.1', tightened_ratio='0.2')
        self.create_plan(name='后建方案', sample_ratio='0.9', tightened_ratio='0.9')
        response = self.fix_batch('B-TIE', 10)
        data = response.json()['data']
        self.assertEqual(data['plan_snapshot']['plan_id'], first.id)
        self.assertEqual(data['sample_size'], 1)

    def test_quantity_out_of_range_not_matched(self):
        self.create_plan(
            name='小批量方案', min_quantity='0', max_quantity='10',
            sample_ratio='0.5', tightened_ratio='0.6',
        )
        response = self.fix_batch('B-OUT', 500)
        self.assertEqual(response.status_code, 400)
        self.assertIn('没有适用', response.json()['message'])

    def test_effective_interval(self):
        now = timezone.now()
        # 未生效
        self.create_plan(
            name='未生效方案',
            effective_from=(now + timedelta(days=1)).isoformat(),
            effective_to=(now + timedelta(days=10)).isoformat(),
        )
        response = self.fix_batch('B-NOT-YET', 10)
        self.assertEqual(response.status_code, 400)

        # 已过期
        self.create_plan(
            name='已过期方案',
            effective_from=(now - timedelta(days=10)).isoformat(),
            effective_to=(now - timedelta(days=1)).isoformat(),
        )
        response = self.fix_batch('B-EXPIRED', 10)
        self.assertEqual(response.status_code, 400)

        # 在生效区间内
        self.create_plan(
            name='生效中方案',
            effective_from=(now - timedelta(days=1)).isoformat(),
            effective_to=(now + timedelta(days=1)).isoformat(),
        )
        response = self.fix_batch('B-ACTIVE', 10)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['plan_snapshot']['plan_name'], '生效中方案')

    def test_draft_plan_not_matched(self):
        self.create_plan(publish=False)
        response = self.fix_batch('B-DRAFT', 10)
        self.assertEqual(response.status_code, 400)

    def test_category_isolated(self):
        other_category = Category.objects.create(name="封存介质", unit=self.unit, created_by=self.user)
        self.create_plan()
        response = self.fix_batch('B-CAT', 10, category_id=other_category.id)
        self.assertEqual(response.status_code, 400)


class InspectionSnapshotTest(InspectionFixture):
    def test_snapshot_freezes_plan_content(self):
        plan = self.create_plan(sample_ratio='0.25', tightened_ratio='0.5')
        response = self.fix_batch('B-SNAP', 40, source='乙供应商')
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['sample_size'], 10)
        self.assertEqual(data['inspection_level'], 'normal')
        self.assertEqual(data['check_items'], CHECK_ITEMS)
        snapshot = data['plan_snapshot']
        self.assertEqual(snapshot['plan_id'], plan.id)
        self.assertEqual(snapshot['applied_ratio'], '0.2500')
        self.assertEqual(snapshot['rounding'], 'ceil')
        self.assertEqual(snapshot['check_items'], CHECK_ITEMS)

    def test_refixed_batch_keeps_original_snapshot(self):
        """旧批次再次核验不套用新方案"""
        self.create_plan(name='旧方案', sample_ratio='0.1', tightened_ratio='0.2')
        first = self.fix_batch('B-KEEP', 100)
        self.assertEqual(first.status_code, 200)
        first_data = first.json()['data']
        self.assertEqual(first_data['sample_size'], 10)

        # 风险上升：撤回旧方案，发布比例更高的新方案
        old_plan = SamplingPlan.objects.get(name='旧方案')
        self.client.post(f"/api/sampling-plans/{old_plan.id}/withdraw/", {'reason': '风险上升'}, format="json")
        self.create_plan(name='新方案', sample_ratio='0.9', tightened_ratio='0.9')

        second = self.fix_batch('B-KEEP', 100)
        self.assertEqual(second.status_code, 200)
        second_data = second.json()['data']
        self.assertEqual(second_data['id'], first_data['id'])
        self.assertEqual(second_data['sample_size'], 10)
        self.assertEqual(second_data['plan_snapshot']['plan_name'], '旧方案')

        # 详情查询同样返回原快照
        detail = self.client.get(f"/api/inspections/{first_data['id']}/")
        self.assertEqual(detail.json()['data']['plan_snapshot']['plan_name'], '旧方案')

        # 新批次才适用新方案
        third = self.fix_batch('B-NEW', 100)
        self.assertEqual(third.json()['data']['plan_snapshot']['plan_name'], '新方案')
        self.assertEqual(third.json()['data']['sample_size'], 90)

    def test_conflicting_batch_info_rejected(self):
        self.create_plan()
        self.fix_batch('B-CONFLICT', 100, source='甲供应商')
        conflict = self.fix_batch('B-CONFLICT', 200)
        self.assertEqual(conflict.status_code, 400)
        conflict = self.fix_batch('B-CONFLICT', 100, source='乙供应商')
        self.assertEqual(conflict.status_code, 400)

    def test_withdrawn_plan_not_matched_for_new_batch(self):
        plan = self.create_plan()
        self.fix_batch('B-BEFORE', 10)
        self.client.post(f"/api/sampling-plans/{plan.id}/withdraw/", {'reason': '停用'}, format="json")
        response = self.fix_batch('B-AFTER', 10)
        self.assertEqual(response.status_code, 400)
        # 旧快照仍可查询
        old = Inspection.objects.get(batch_no='B-BEFORE')
        detail = self.client.get(f"/api/inspections/{old.id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()['data']['plan_snapshot']['plan_name'], plan.name)


class TightenedInspectionTest(InspectionFixture):
    """加严复检：同品类同来源上次判定不合格，下一批自动加严"""

    def test_tightened_after_failure(self):
        self.create_plan(sample_ratio='0.1', tightened_ratio='0.5')
        first = self.fix_batch('B-FAIL', 100, source='甲供应商')
        first_id = first.json()['data']['id']
        self.assertEqual(first.json()['data']['inspection_level'], 'normal')

        completed = self.complete_batch(first_id, results=[
            {'name': '外观', 'result': 'fail'},
            {'name': '封存标识', 'result': 'pass'},
        ])
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.json()['data']['conclusion'], 'unqualified')

        second = self.fix_batch('B-AFTER-FAIL', 100, source='甲供应商')
        data = second.json()['data']
        self.assertEqual(data['inspection_level'], 'tightened')
        self.assertEqual(data['sample_size'], 50)
        self.assertEqual(data['tightened_trigger'], first_id)
        self.assertEqual(data['plan_snapshot']['applied_ratio'], '0.5000')

    def test_back_to_normal_after_tightened_pass(self):
        self.create_plan(sample_ratio='0.1', tightened_ratio='0.5')
        first_id = self.fix_batch('B-F1', 100, source='甲供应商').json()['data']['id']
        self.complete_batch(first_id, results=[
            {'name': '外观', 'result': 'fail'},
            {'name': '封存标识', 'result': 'fail'},
        ])
        second_id = self.fix_batch('B-F2', 100, source='甲供应商').json()['data']['id']
        self.assertEqual(Inspection.objects.get(pk=second_id).inspection_level, 'tightened')
        self.complete_batch(second_id)

        third = self.fix_batch('B-F3', 100, source='甲供应商')
        self.assertEqual(third.json()['data']['inspection_level'], 'normal')
        self.assertEqual(third.json()['data']['sample_size'], 10)

    def test_tightening_scoped_to_source(self):
        self.create_plan(sample_ratio='0.1', tightened_ratio='0.5')
        first_id = self.fix_batch('B-S1', 100, source='甲供应商').json()['data']['id']
        self.complete_batch(first_id, results=[
            {'name': '外观', 'result': 'fail'},
            {'name': '封存标识', 'result': 'pass'},
        ])
        # 其他来源不受影响
        other = self.fix_batch('B-S2', 100, source='乙供应商')
        self.assertEqual(other.json()['data']['inspection_level'], 'normal')

    def test_pending_failure_does_not_tighten(self):
        """未完成判定的批次不触发加严"""
        self.create_plan(sample_ratio='0.1', tightened_ratio='0.5')
        self.fix_batch('B-PENDING', 100, source='甲供应商')
        nxt = self.fix_batch('B-PENDING-2', 100, source='甲供应商')
        self.assertEqual(nxt.json()['data']['inspection_level'], 'normal')


class InspectionCompleteTest(InspectionFixture):
    def setUp(self):
        super().setUp()
        self.create_plan(sample_ratio='0.1', tightened_ratio='0.2')
        self.inspection_id = self.fix_batch('B-DONE', 10).json()['data']['id']

    def test_all_pass_is_qualified(self):
        response = self.complete_batch(self.inspection_id)
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['status'], 'completed')
        self.assertEqual(data['conclusion'], 'qualified')
        self.assertEqual(len(data['item_results']), 2)
        self.assertIsNotNone(data['completed_at'])

    def test_any_fail_is_unqualified(self):
        response = self.complete_batch(self.inspection_id, results=[
            {'name': '外观', 'result': 'pass'},
            {'name': '封存标识', 'result': 'fail'},
        ])
        self.assertEqual(response.json()['data']['conclusion'], 'unqualified')

    def test_results_must_cover_snapshot_items(self):
        missing = self.complete_batch(self.inspection_id, results=[
            {'name': '外观', 'result': 'pass'},
        ])
        self.assertEqual(missing.status_code, 400)
        extra = self.complete_batch(self.inspection_id, results=[
            {'name': '外观', 'result': 'pass'},
            {'name': '封存标识', 'result': 'pass'},
            {'name': '不存在项', 'result': 'pass'},
        ])
        self.assertEqual(extra.status_code, 400)
        invalid = self.complete_batch(self.inspection_id, results=[
            {'name': '外观', 'result': 'unknown'},
            {'name': '封存标识', 'result': 'pass'},
        ])
        self.assertEqual(invalid.status_code, 400)
        duplicated = self.complete_batch(self.inspection_id, results=[
            {'name': '外观', 'result': 'pass'},
            {'name': '外观', 'result': 'pass'},
            {'name': '封存标识', 'result': 'pass'},
        ])
        self.assertEqual(duplicated.status_code, 400)

    def test_cannot_complete_twice(self):
        self.complete_batch(self.inspection_id)
        again = self.complete_batch(self.inspection_id)
        self.assertEqual(again.status_code, 400)


class InspectionAPITest(InspectionFixture):
    def test_list_and_filter(self):
        self.create_plan()
        self.fix_batch('B-L1', 10, source='甲供应商')
        self.fix_batch('B-L2', 20, source='乙供应商')
        response = self.client.get("/api/inspections/")
        self.assertEqual(response.json()['data']['total'], 2)
        response = self.client.get("/api/inspections/?batch_no=B-L1")
        self.assertEqual(response.json()['data']['total'], 1)
        self.assertEqual(response.json()['data']['list'][0]['batch_no'], 'B-L1')

    def test_plan_list_filter_by_status(self):
        self.create_plan(name='已发布方案')
        self.create_plan(publish=False, name='草案方案')
        published = self.client.get("/api/sampling-plans/?status=published")
        draft = self.client.get("/api/sampling-plans/?status=draft")
        self.assertEqual(published.json()['data']['total'], 1)
        self.assertEqual(draft.json()['data']['total'], 1)

    def test_requires_authentication(self):
        anonymous = APIClient()
        self.assertEqual(anonymous.get("/api/sampling-plans/").status_code, 401)
        self.assertEqual(anonymous.get("/api/inspections/").status_code, 401)
        self.assertEqual(anonymous.post("/api/inspections/fix/", {}, format="json").status_code, 401)

    def test_fix_validates_input(self):
        self.create_plan()
        bad = self.fix_batch('B-BAD', 0)
        self.assertEqual(bad.status_code, 400)
        bad = self.fix_batch('B-BAD', 10, category_id=99999)
        self.assertEqual(bad.status_code, 400)
