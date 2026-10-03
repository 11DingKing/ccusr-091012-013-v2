"""
抽检方案管理测试

覆盖需求中的一致性要点：
- 草案 / 发布 / 撤回生命周期与生效区间；
- 小批量取整（向上/四舍五入/向下、最小样本数、不超过批量）；
- 加严复检（风险上升自动加严、复检沿用冻结规则）；
- 规则重叠（同严格度区间重叠拒绝、跨严格度加严优先）；
- 方案撤回后旧批次快照不变；
- 旧批次再次查询不套用新方案（快照幂等 + 新版本接替）。
"""
import decimal
from datetime import timedelta

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.backends import generate_token
from apps.authentication.models import User
from apps.warehouse.models import Category, Goods, Unit, Variety
from .models import (
    InspectionPlan, InspectionSnapshot, SamplingRule,
    PLAN_DRAFT, PLAN_PUBLISHED, PLAN_WITHDRAWN,
    SEVERITY_NORMAL, SEVERITY_TIGHTENED,
    ROUND_UP, ROUND_HALF_UP, ROUND_DOWN,
    RESULT_PASS, RESULT_FAIL, RESULT_CONDITIONAL, RESULT_PENDING,
)
from . import services


def make_rule_payload(**overrides):
    """一条最常用的正常规则：10%、向上取整、批量 1~∞"""
    payload = {
        'severity': SEVERITY_NORMAL,
        'batch_min': 1, 'batch_max': 0,
        'sample_ratio': '0.10', 'fixed_sample_count': None,
        'min_sample_count': 1, 'rounding_rule': ROUND_UP,
    }
    payload.update(overrides)
    return payload


def make_plan_payload(**overrides):
    payload = {
        'code': 'SP-001',
        'name': '常规抽检方案',
        'version': '1.0',
        'category': None,  # 由测试填充
        'source': '',
        'risk_level': '',
        'accept_count': 0,
        'reject_count': 1,
        'rules': [make_rule_payload()],
        'items': [{'name': '外观检查', 'is_critical': True, 'sort_order': 0}],
    }
    payload.update(overrides)
    return payload


class InspectionFixture(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('insp-user', 'testpass123', role='admin')
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {generate_token(self.user)}')
        self.unit = Unit.objects.create(name='件', created_by=self.user)
        self.category = Category.objects.create(
            name='封存介质', unit=self.unit, created_by=self.user)
        self.variety = Variety.objects.create(
            name='加密硬盘', category=self.category, created_by=self.user)
        self.goods = Goods.objects.create(
            variety=self.variety, name='取证硬盘 A', code='HD-001', quantity=100)

    def create_published_plan(self, code='SP-001', **plan_overrides):
        payload = make_plan_payload(code=code, category=self.category.id, **plan_overrides)
        plan = services.create_draft(payload, user=self.user)
        return services.publish_plan(plan, user=self.user), payload


# ==================== 取整规则 ====================

class RoundingServiceTest(TestCase):
    def _rule(self, ratio, rounding, batch_min=1, fixed=None, minimum=1):
        return SamplingRule(
            severity=SEVERITY_NORMAL, batch_min=batch_min, batch_max=0,
            sample_ratio=ratio, fixed_sample_count=fixed,
            min_sample_count=minimum, rounding_rule=rounding)

    def test_small_batch_ceil_never_zero(self):
        rule = self._rule(decimal.Decimal('0.10'), ROUND_UP)
        # 3 × 10% = 0.3，向上取整为 1（小批量至少抽 1 件）
        self.assertEqual(services.compute_sample_count(rule, 3), 1)

    def test_rounding_modes(self):
        # 25 × 0.10 = 2.5
        rule = self._rule(decimal.Decimal('0.10'), ROUND_UP)
        self.assertEqual(services.compute_sample_count(rule, 25), 3)
        rule.rounding_rule = ROUND_HALF_UP
        self.assertEqual(services.compute_sample_count(rule, 25), 3)
        # 24 × 0.10 = 2.4
        rule.rounding_rule = ROUND_DOWN
        self.assertEqual(services.compute_sample_count(rule, 24), 2)
        rule.rounding_rule = ROUND_HALF_UP
        self.assertEqual(services.compute_sample_count(rule, 24), 2)

    def test_sample_capped_by_batch_and_lifted_by_minimum(self):
        # 比例 50% 但最少抽 10 件
        rule = self._rule(decimal.Decimal('0.50'), ROUND_UP, minimum=10)
        self.assertEqual(services.compute_sample_count(rule, 4), 4)  # 不超过批量
        self.assertEqual(services.compute_sample_count(rule, 100), 50)

    def test_fixed_count_acts_as_floor(self):
        rule = self._rule(decimal.Decimal('0.10'), ROUND_UP, fixed=20)
        self.assertEqual(services.compute_sample_count(rule, 100), 20)  # max(20, 10)
        self.assertEqual(services.compute_sample_count(rule, 500), 50)

    def test_invalid_batch_quantity(self):
        rule = self._rule(decimal.Decimal('0.10'), ROUND_UP)
        with self.assertRaises(services.InspectionError):
            services.compute_sample_count(rule, 0)


# ==================== 规则重叠 ====================

class RuleOverlapTest(InspectionFixture):
    def test_same_severity_overlap_rejected_on_publish(self):
        payload = make_plan_payload(
            code='SP-OVL', category=self.category.id,
            rules=[
                make_rule_payload(batch_min=1, batch_max=100),
                make_rule_payload(batch_min=50, batch_max=200),
            ])
        plan = services.create_draft(payload, user=self.user)
        with self.assertRaises(services.InspectionError):
            services.publish_plan(plan, user=self.user)

    def test_adjacent_intervals_touching_is_overlap(self):
        # 端点含于双方区间：[1,100] 与 [100,200] 在 100 处重叠
        rules = [
            SamplingRule(severity=SEVERITY_NORMAL, batch_min=1, batch_max=100),
            SamplingRule(severity=SEVERITY_NORMAL, batch_min=100, batch_max=200),
        ]
        with self.assertRaises(services.InspectionError):
            services.validate_rule_intervals(rules)

    def test_gap_intervals_valid(self):
        rules = [
            SamplingRule(severity=SEVERITY_NORMAL, batch_min=1, batch_max=99),
            SamplingRule(severity=SEVERITY_NORMAL, batch_min=100, batch_max=0),
        ]
        services.validate_rule_intervals(rules)  # 不抛异常

    def test_cross_severity_overlap_allowed_and_tightened_wins(self):
        plan, _ = self.create_published_plan(
            code='SP-TS',
            rules=[
                make_rule_payload(severity=SEVERITY_NORMAL, batch_min=1, batch_max=0,
                                  sample_ratio='0.10'),
                make_rule_payload(severity=SEVERITY_TIGHTENED, batch_min=1, batch_max=0,
                                  sample_ratio='0.30'),
            ])
        rule, severity = services.resolve_rule(plan, 100, prefer_tightened=True)
        self.assertEqual(severity, SEVERITY_TIGHTENED)
        self.assertEqual(services.compute_sample_count(rule, 100), 30)
        # 不要求加严时取正常规则
        rule, severity = services.resolve_rule(plan, 100, prefer_tightened=False)
        self.assertEqual(severity, SEVERITY_NORMAL)
        self.assertEqual(services.compute_sample_count(rule, 100), 10)

    def test_risky_goods_auto_tightened_on_fix(self):
        self.create_published_plan(
            code='SP-RISK',
            rules=[
                make_rule_payload(severity=SEVERITY_NORMAL, sample_ratio='0.10'),
                make_rule_payload(severity=SEVERITY_TIGHTENED, sample_ratio='0.50'),
            ])
        snapshot, created = services.fix_snapshot(
            goods=self.goods, batch_no='B-RISK', batch_quantity=100,
            risk_level='high', severity='auto', user=self.user)
        self.assertTrue(created)
        self.assertEqual(snapshot.severity, SEVERITY_TIGHTENED)
        self.assertEqual(snapshot.sample_count, 50)

    def test_inconsistent_overlap_in_db_raises(self):
        plan, _ = self.create_published_plan(code='SP-DB')
        # 绕过服务层制造同严格度重叠数据
        SamplingRule.objects.create(
            plan=plan, severity=SEVERITY_NORMAL, batch_min=1, batch_max=100,
            sample_ratio=decimal.Decimal('0.1'), rounding_rule=ROUND_UP)
        with self.assertRaises(services.RuleOverlapError):
            services.resolve_rule(plan, 50)


# ==================== 生命周期与生效区间 ====================

class PlanLifecycleTest(InspectionFixture):
    def test_draft_publish_withdraw(self):
        payload = make_plan_payload(category=self.category.id)
        plan = services.create_draft(payload, user=self.user)
        self.assertEqual(plan.status, PLAN_DRAFT)
        self.assertTrue(plan.is_editable)
        services.publish_plan(plan, user=self.user)
        plan.refresh_from_db()
        self.assertEqual(plan.status, PLAN_PUBLISHED)
        self.assertIsNotNone(plan.effective_from)
        # 已发布不可编辑
        with self.assertRaises(services.InspectionError):
            services.update_draft(plan, payload)
        services.withdraw_plan(plan, reason='标准废止', user=self.user)
        plan.refresh_from_db()
        self.assertEqual(plan.status, PLAN_WITHDRAWN)
        self.assertIsNotNone(plan.effective_to)
        with self.assertRaises(services.InspectionError):
            services.publish_plan(plan, user=self.user)

    def test_publish_requires_rule_and_item(self):
        # 序列化器会拦截空规则；服务层同样兜底
        from .models import InspectionItem
        bare = InspectionPlan.objects.create(
            code='SP-BARE', name='空方案', category=self.category,
            accept_count=0, reject_count=1, created_by=self.user)
        with self.assertRaises(services.InspectionError):
            services.publish_plan(bare, user=self.user)
        SamplingRule.objects.create(
            plan=bare, severity=SEVERITY_NORMAL, batch_min=1, batch_max=0,
            sample_ratio=decimal.Decimal('0.1'), rounding_rule=ROUND_UP)
        with self.assertRaises(services.InspectionError):
            services.publish_plan(bare, user=self.user)  # 仍缺检查项
        InspectionItem.objects.create(plan=bare, name='外观')
        services.publish_plan(bare, user=self.user)  # 补齐后可发布

    def test_new_version_closes_old_effective_interval(self):
        v1, _ = self.create_published_plan(code='SP-VER')
        t0 = timezone.now() - timedelta(days=2)
        # 重新构造一个已生效两天的 v1
        InspectionPlan.objects.filter(pk=v1.pk).update(
            effective_from=t0, effective_to=None, published_at=t0)
        v1.refresh_from_db()

        v2 = services.create_draft(
            make_plan_payload(code='SP-VER-2', category=self.category.id),
            user=self.user)
        t1 = timezone.now()
        services.publish_plan(v2, effective_from=t1, user=self.user)
        v1.refresh_from_db()
        # 旧版本生效区间在新版本生效时闭合
        self.assertEqual(v1.effective_to, t1)

        # 旧时刻仍由 v1 覆盖，新时刻由 v2 覆盖
        self.assertEqual(
            services.find_effective_plan(self.category.id, '', at=t0 + timedelta(hours=1)).pk,
            v1.pk)
        self.assertEqual(
            services.find_effective_plan(self.category.id, '', at=t1 + timedelta(hours=1)).pk,
            v2.pk)

    def test_future_revision_does_not_cut_current(self):
        v1, _ = self.create_published_plan(code='SP-NOW')
        future = timezone.now() + timedelta(days=10)
        v2 = services.create_draft(
            make_plan_payload(code='SP-NEW', category=self.category.id), user=self.user)
        services.publish_plan(v2, effective_from=future, user=self.user)
        v1.refresh_from_db()
        # v1 当前仍生效，生效区间在 future 时刻被新版本接替
        self.assertEqual(v1.effective_to, future)
        self.assertEqual(
            services.find_effective_plan(self.category.id, '').pk, v1.pk)
        self.assertEqual(
            services.find_effective_plan(
                self.category.id, '', at=future + timedelta(hours=1)).pk, v2.pk)

    def test_overlapping_same_scope_version_inversion_rejected(self):
        # 已存在一个未来生效的同范围方案，再发立即生效的版本应拒绝
        future = timezone.now() + timedelta(days=10)
        v_future = services.create_draft(
            make_plan_payload(code='SP-FUT', category=self.category.id), user=self.user)
        services.publish_plan(v_future, effective_from=future, user=self.user)
        v_now = services.create_draft(
            make_plan_payload(code='SP-NOW2', category=self.category.id), user=self.user)
        with self.assertRaises(services.PlanOverlapError):
            services.publish_plan(v_now, user=self.user)

    def test_incomparable_scopes_rejected(self):
        # 一方限定来源、另一方限定风险：存在物资同时命中，不可比较 → 拒绝
        a = services.create_draft(
            make_plan_payload(code='SP-SRC', category=self.category.id,
                              source='供应商甲'), user=self.user)
        services.publish_plan(a, user=self.user)
        b = services.create_draft(
            make_plan_payload(code='SP-RSK', category=self.category.id,
                              risk_level='high'), user=self.user)
        with self.assertRaises(services.PlanOverlapError):
            services.publish_plan(b, user=self.user)

    def test_more_specific_scope_coexists_and_wins(self):
        generic, _ = self.create_published_plan(code='SP-GEN')
        specific = services.create_draft(
            make_plan_payload(code='SP-SPC', category=self.category.id,
                              source='供应商甲'), user=self.user)
        services.publish_plan(specific, user=self.user)
        chosen = services.find_effective_plan(self.category.id, '供应商甲')
        self.assertEqual(chosen.pk, specific.pk)
        chosen_other = services.find_effective_plan(self.category.id, '供应商乙')
        self.assertEqual(chosen_other.pk, generic.pk)

    def test_different_sources_do_not_clash(self):
        a = services.create_draft(
            make_plan_payload(code='SP-A', category=self.category.id,
                              source='供应商甲'), user=self.user)
        services.publish_plan(a, user=self.user)
        b = services.create_draft(
            make_plan_payload(code='SP-B', category=self.category.id,
                              source='供应商乙'), user=self.user)
        services.publish_plan(b, user=self.user)  # 来源不同，不构成冲突
        self.assertEqual(
            services.find_effective_plan(self.category.id, '供应商甲').pk, a.pk)
        self.assertEqual(
            services.find_effective_plan(self.category.id, '供应商乙').pk, b.pk)


# ==================== 快照固定与版本隔离 ====================

class SnapshotFixTest(InspectionFixture):
    def test_fix_freezes_sample_count_items_and_judgement_thresholds(self):
        plan, _ = self.create_published_plan(
            code='SP-FRZ',
            rules=[make_rule_payload(sample_ratio='0.10')],
            items=[
                {'name': '外观', 'is_critical': True, 'sort_order': 0},
                {'name': '通电测试', 'is_critical': False, 'sort_order': 1,
                 'standard': '30 分钟无宕机'},
            ],
            accept_count=1, reject_count=3)
        snapshot, created = services.fix_snapshot(
            goods=self.goods, batch_no='B-001', batch_quantity=25,
            source='供应商甲', user=self.user)
        self.assertTrue(created)
        self.assertEqual(snapshot.sample_count, 3)  # ceil(2.5)
        self.assertEqual(snapshot.plan_code, 'SP-FRZ')
        self.assertEqual(snapshot.category_name, '封存介质')
        self.assertEqual(snapshot.accept_count, 1)
        self.assertEqual(snapshot.reject_count, 3)
        names = list(snapshot.items.values_list('name', flat=True))
        self.assertEqual(names, ['外观', '通电测试'])
        self.assertTrue(snapshot.items.get(name='外观').is_critical)

    def test_fix_is_idempotent_and_never_applies_new_plan(self):
        v1, _ = self.create_published_plan(code='SP-OLD')
        snapshot1, created1 = services.fix_snapshot(
            goods=self.goods, batch_no='B-FIX', batch_quantity=100, user=self.user)
        self.assertTrue(created1)

        # 发布比例更高的新版本
        v2 = services.create_draft(
            make_plan_payload(code='SP-NEWV', category=self.category.id,
                              rules=[make_rule_payload(sample_ratio='0.50')]),
            user=self.user)
        services.publish_plan(v2, user=self.user)

        # 同一批次再次固定 → 返回原快照、原方案、原样本数
        snapshot2, created2 = services.fix_snapshot(
            goods=self.goods, batch_no='B-FIX', batch_quantity=100, user=self.user)
        self.assertFalse(created2)
        self.assertEqual(snapshot2.pk, snapshot1.pk)
        self.assertEqual(snapshot2.plan_id, v1.pk)
        self.assertEqual(snapshot2.sample_count, 10)

        # 不同批次才套用新方案
        snapshot3, created3 = services.fix_snapshot(
            goods=self.goods, batch_no='B-FIX2', batch_quantity=100, user=self.user)
        self.assertTrue(created3)
        self.assertEqual(snapshot3.plan_id, v2.pk)
        self.assertEqual(snapshot3.sample_count, 50)

    def test_concurrent_fix_respects_uniqueness(self):
        self.create_published_plan(code='SP-CON')
        services.fix_snapshot(
            goods=self.goods, batch_no='B-C', batch_quantity=10, user=self.user)
        with self.assertRaises(IntegrityError):
            InspectionSnapshot.objects.create(
                plan=InspectionPlan.objects.get(code='SP-CON'),
                goods=self.goods, batch_no='B-C', category_name='封存介质',
                batch_quantity=10, plan_code='SP-CON', plan_name='x',
                plan_version='1.0', sample_count=1, rounding_rule=ROUND_UP)

    def test_no_effective_plan(self):
        with self.assertRaises(services.NoEffectivePlanError):
            services.fix_snapshot(
                goods=self.goods, batch_no='B-X', batch_quantity=10, user=self.user)

    def test_withdrawn_plan_unavailable_but_old_snapshot_intact(self):
        plan, _ = self.create_published_plan(code='SP-WD')
        snapshot, _ = services.fix_snapshot(
            goods=self.goods, batch_no='B-WD', batch_quantity=50, user=self.user)
        services.withdraw_plan(plan, reason='停用', user=self.user)
        # 新批次无法固定
        with self.assertRaises(services.NoEffectivePlanError):
            services.fix_snapshot(
                goods=self.goods, batch_no='B-WD2', batch_quantity=50, user=self.user)
        # 旧批次快照原样可查
        again = services.get_fixed_snapshot(self.goods, 'B-WD')
        self.assertEqual(again.pk, snapshot.pk)
        self.assertEqual(again.sample_count, 5)


# ==================== 判定 ====================

class JudgeTest(InspectionFixture):
    def _judge_inputs(self, snapshot, defects_by_name):
        rows = []
        for item in snapshot.items.all():
            rows.append({
                'item_id': item.pk,
                'checked_count': snapshot.sample_count,
                'defect_count': defects_by_name.get(item.name, 0),
            })
        return rows

    def test_pass_fail_and_conditional_bands(self):
        plan, _ = self.create_published_plan(
            code='SP-J1', accept_count=2, reject_count=4,
            items=[{'name': '项目一', 'is_critical': False}])
        snapshot, _ = services.fix_snapshot(
            goods=self.goods, batch_no='BJ-1', batch_quantity=100, user=self.user)

        services.judge_snapshot(
            snapshot, self._judge_inputs(snapshot, {'项目一': 2}), user=self.user)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.result, RESULT_PASS)

    def test_reject_band(self):
        plan, _ = self.create_published_plan(
            code='SP-J2', accept_count=2, reject_count=4,
            items=[{'name': '项目一', 'is_critical': False}])
        snapshot, _ = services.fix_snapshot(
            goods=self.goods, batch_no='BJ-2', batch_quantity=100, user=self.user)
        services.judge_snapshot(
            snapshot, self._judge_inputs(snapshot, {'项目一': 4}), user=self.user)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.result, RESULT_FAIL)

    def test_conditional_band(self):
        plan, _ = self.create_published_plan(
            code='SP-J3', accept_count=2, reject_count=4,
            items=[{'name': '项目一', 'is_critical': False}])
        snapshot, _ = services.fix_snapshot(
            goods=self.goods, batch_no='BJ-3', batch_quantity=100, user=self.user)
        services.judge_snapshot(
            snapshot, self._judge_inputs(snapshot, {'项目一': 3}), user=self.user)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.result, RESULT_CONDITIONAL)

    def test_critical_item_fails_directly(self):
        plan, _ = self.create_published_plan(
            code='SP-J4', accept_count=5, reject_count=10,
            items=[{'name': '关键项', 'is_critical': True}])
        snapshot, _ = services.fix_snapshot(
            goods=self.goods, batch_no='BJ-4', batch_quantity=100, user=self.user)
        services.judge_snapshot(
            snapshot, self._judge_inputs(snapshot, {'关键项': 1}), user=self.user)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.result, RESULT_FAIL)

    def test_cannot_judge_twice(self):
        plan, _ = self.create_published_plan(code='SP-J5')
        snapshot, _ = services.fix_snapshot(
            goods=self.goods, batch_no='BJ-5', batch_quantity=100, user=self.user)
        rows = self._judge_inputs(snapshot, {})
        services.judge_snapshot(snapshot, rows, user=self.user)
        with self.assertRaises(services.InspectionError):
            services.judge_snapshot(snapshot, rows, user=self.user)

    def test_checked_count_cannot_exceed_sample_count(self):
        plan, _ = self.create_published_plan(code='SP-J6')
        snapshot, _ = services.fix_snapshot(
            goods=self.goods, batch_no='BJ-6', batch_quantity=100, user=self.user)
        item = snapshot.items.first()
        with self.assertRaises(services.InspectionError):
            services.judge_snapshot(
                snapshot,
                [{'item_id': item.pk, 'checked_count': 999, 'defect_count': 0}],
                user=self.user)

    def test_must_cover_all_items(self):
        plan, _ = self.create_published_plan(
            code='SP-J7', items=[
                {'name': '一', 'sort_order': 0}, {'name': '二', 'sort_order': 1}])
        snapshot, _ = services.fix_snapshot(
            goods=self.goods, batch_no='BJ-7', batch_quantity=100, user=self.user)
        item = snapshot.items.first()
        with self.assertRaises(services.InspectionError):
            services.judge_snapshot(
                snapshot,
                [{'item_id': item.pk, 'checked_count': 1, 'defect_count': 0}],
                user=self.user)


# ==================== 加严复检 ====================

class RecheckTest(InspectionFixture):
    def test_recheck_uses_frozen_recheck_rule(self):
        # 正常 10%，加严复检 50%（正常规则指向加严规则，序号 1）
        plan, _ = self.create_published_plan(
            code='SP-RC1',
            accept_count=0, reject_count=1,
            rules=[
                make_rule_payload(severity=SEVERITY_NORMAL, sample_ratio='0.10',
                                  recheck_index=1),
                make_rule_payload(severity=SEVERITY_TIGHTENED, sample_ratio='0.50'),
            ])
        snapshot, _ = services.fix_snapshot(
            goods=self.goods, batch_no='BR-1', batch_quantity=100, user=self.user)
        self.assertEqual(snapshot.sample_count, 10)
        services.judge_snapshot(
            snapshot,
            [{'item_id': i.pk, 'checked_count': 10, 'defect_count': 1}
             for i in snapshot.items.all()],
            user=self.user)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.result, RESULT_FAIL)

        recheck, created = services.start_recheck(snapshot, user=self.user)
        self.assertTrue(created)
        self.assertEqual(recheck.recheck_of_id, snapshot.pk)
        self.assertEqual(recheck.severity, SEVERITY_TIGHTENED)
        self.assertEqual(recheck.sample_count, 50)
        self.assertEqual(recheck.result, RESULT_PENDING)
        # 首检快照保持不变
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.sample_count, 10)

        # 复检幂等
        again, created2 = services.start_recheck(snapshot, user=self.user)
        self.assertFalse(created2)
        self.assertEqual(again.pk, recheck.pk)

    def test_recheck_fallback_after_plan_change_uses_frozen_data(self):
        plan, _ = self.create_published_plan(
            code='SP-RC2',
            rules=[make_rule_payload(severity=SEVERITY_NORMAL, sample_ratio='0.10')])
        snapshot, _ = services.fix_snapshot(
            goods=self.goods, batch_no='BR-2', batch_quantity=100, user=self.user)
        services.judge_snapshot(
            snapshot,
            [{'item_id': i.pk, 'checked_count': 10, 'defect_count': 1}
             for i in snapshot.items.all()],
            user=self.user)

        # 方案撤回后复检仍依据冻结的规则执行（10% 向上取整）
        services.withdraw_plan(plan, user=self.user)
        recheck, _ = services.start_recheck(snapshot, user=self.user)
        self.assertEqual(recheck.plan_id, plan.pk)
        self.assertEqual(recheck.sample_count, 10)

    def test_only_failed_snapshot_can_recheck(self):
        plan, _ = self.create_published_plan(code='SP-RC3')
        snapshot, _ = services.fix_snapshot(
            goods=self.goods, batch_no='BR-3', batch_quantity=100, user=self.user)
        with self.assertRaises(services.InspectionError):
            services.start_recheck(snapshot, user=self.user)

    def test_recheck_snapshot_cannot_recheck_again(self):
        plan, _ = self.create_published_plan(code='SP-RC4')
        snapshot, _ = services.fix_snapshot(
            goods=self.goods, batch_no='BR-4', batch_quantity=100, user=self.user)
        services.judge_snapshot(
            snapshot,
            [{'item_id': i.pk, 'checked_count': 10, 'defect_count': 1}
             for i in snapshot.items.all()],
            user=self.user)
        recheck, _ = services.start_recheck(snapshot, user=self.user)
        with self.assertRaises(services.InspectionError):
            services.start_recheck(recheck, user=self.user)


# ==================== 方案草案编辑与复检链校验 ====================

class DraftEditingTest(InspectionFixture):
    def test_full_replace_on_update(self):
        plan = services.create_draft(
            make_plan_payload(category=self.category.id), user=self.user)
        payload = make_plan_payload(
            category=self.category.id,
            rules=[
                make_rule_payload(severity=SEVERITY_NORMAL, batch_min=1, batch_max=99,
                                  sample_ratio='0.20'),
                make_rule_payload(severity=SEVERITY_NORMAL, batch_min=100, batch_max=0,
                                  sample_ratio='0.30'),
            ],
            items=[
                {'name': '新检查项', 'sort_order': 0},
                {'name': '另一项', 'sort_order': 1},
            ])
        services.update_draft(plan, payload)
        self.assertEqual(plan.rules.count(), 2)
        self.assertEqual(plan.items.count(), 2)

    def test_recheck_index_cycle_rejected(self):
        payload = make_plan_payload(
            code='SP-CYC', category=self.category.id,
            rules=[
                make_rule_payload(severity=SEVERITY_NORMAL, batch_min=1, batch_max=99,
                                  recheck_index=1),
                make_rule_payload(severity=SEVERITY_TIGHTENED, batch_min=100, batch_max=0,
                                  recheck_index=0),
            ])
        with self.assertRaises(services.InspectionError):
            services.create_draft(payload, user=self.user)

    def test_recheck_index_out_of_range_rejected(self):
        payload = make_plan_payload(
            code='SP-OOR', category=self.category.id,
            rules=[make_rule_payload(recheck_index=5)])
        with self.assertRaises(services.InspectionError):
            services.create_draft(payload, user=self.user)

    def test_self_recheck_is_allowed(self):
        # 自指：复检沿用本规则（加倍比例）重新抽样
        plan = services.create_draft(
            make_plan_payload(
                code='SP-SELF', category=self.category.id,
                rules=[make_rule_payload(severity=SEVERITY_TIGHTENED,
                                         sample_ratio='0.30', recheck_index=0)]),
            user=self.user)
        services.publish_plan(plan, user=self.user)
        self.assertEqual(plan.rules.count(), 1)


# ==================== API 端到端 ====================

class InspectionAPITest(InspectionFixture):
    def test_full_flow_api(self):
        # 1. 创建草案
        payload = make_plan_payload(
            category=self.category.id,
            rules=[
                make_rule_payload(severity=SEVERITY_NORMAL, sample_ratio='0.10',
                                  recheck_index=1),
                make_rule_payload(severity=SEVERITY_TIGHTENED, sample_ratio='0.40'),
            ],
            items=[{'name': '外观', 'is_critical': True}],
            accept_count=0, reject_count=2)
        resp = self.client.post('/api/inspection/plans/', payload, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        plan_id = resp.json()['data']['id']

        # 2. 发布
        resp = self.client.post(f'/api/inspection/plans/{plan_id}/publish/',
                                {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['data']['status'], PLAN_PUBLISHED)

        # 3. 到场核验固定快照（高风险自动加严）
        resp = self.client.post('/api/inspection/snapshots/fix/', {
            'goods': self.goods.id, 'batch_no': 'B-API', 'batch_quantity': 100,
            'source': '', 'risk_level': 'high', 'severity': 'auto',
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        snap = resp.json()['data']
        self.assertEqual(snap['severity'], SEVERITY_TIGHTENED)
        self.assertEqual(snap['sample_count'], 40)

        # 4. 重复固定返回同一条
        resp2 = self.client.post('/api/inspection/snapshots/fix/', {
            'goods': self.goods.id, 'batch_no': 'B-API', 'batch_quantity': 100,
        }, format='json')
        self.assertEqual(resp2.json()['data']['id'], snap['id'])

        # 5. 判定：关键项不合格 → 不合格
        item_id = snap['items'][0]['id']
        resp = self.client.post(f"/api/inspection/snapshots/{snap['id']}/judge/", {
            'items': [{'item_id': item_id, 'checked_count': 40, 'defect_count': 1}],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['data']['result'], RESULT_FAIL)

        # 6. 加严复检
        resp = self.client.post(
            f"/api/inspection/snapshots/{snap['id']}/recheck/", {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        recheck = resp.json()['data']
        self.assertEqual(recheck['recheck_of'], snap['id'])
        self.assertEqual(recheck['sample_count'], 40)  # 复检规则 40%

        # 7. 批次查询返回首检 + 复检，且不受方案撤回影响
        resp = self.client.post(f'/api/inspection/plans/{plan_id}/withdraw/',
                                {'reason': '换版'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        resp = self.client.get(
            f'/api/inspection/snapshots/batch/?goods={self.goods.id}&batch_no=B-API')
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()['data']
        self.assertEqual(data['first']['plan_code'], 'SP-001')
        self.assertEqual(len(data['rechecks']), 1)

    def test_create_plan_validates_overlap(self):
        resp = self.client.post('/api/inspection/plans/', make_plan_payload(
            code='SP-API-OVL', category=self.category.id,
            rules=[
                make_rule_payload(batch_min=1, batch_max=100),
                make_rule_payload(batch_min=50, batch_max=200),
            ]), format='json')
        # 草案允许先存，发布时拦截
        self.assertEqual(resp.status_code, 200, resp.content)
        plan_id = resp.json()['data']['id']
        resp = self.client.post(f'/api/inspection/plans/{plan_id}/publish/',
                                {}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_old_batch_keeps_old_plan_after_new_version_api(self):
        payload = make_plan_payload(category=self.category.id)
        resp = self.client.post('/api/inspection/plans/', payload, format='json')
        v1_id = resp.json()['data']['id']
        self.client.post(f'/api/inspection/plans/{v1_id}/publish/', {}, format='json')
        self.client.post('/api/inspection/snapshots/fix/', {
            'goods': self.goods.id, 'batch_no': 'B-OLD', 'batch_quantity': 30,
        }, format='json')

        # 新版本 100% 抽检
        resp = self.client.post('/api/inspection/plans/', make_plan_payload(
            code='SP-002', category=self.category.id,
            rules=[make_rule_payload(sample_ratio='1.00')]), format='json')
        v2_id = resp.json()['data']['id']
        self.client.post(f'/api/inspection/plans/{v2_id}/publish/', {}, format='json')

        resp = self.client.get(
            f'/api/inspection/snapshots/batch/?goods={self.goods.id}&batch_no=B-OLD')
        data = resp.json()['data']
        self.assertEqual(data['first']['plan_code'], 'SP-001')
        self.assertEqual(data['first']['sample_count'], 3)  # ceil(30*0.1)

    def test_requires_authentication(self):
        client = APIClient()
        self.assertEqual(client.get('/api/inspection/plans/').status_code, 401)
        self.assertEqual(
            client.post('/api/inspection/snapshots/fix/', {}, format='json').status_code,
            401)
