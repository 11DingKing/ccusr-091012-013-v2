"""
抽检方案管理视图
"""
import logging

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from apps.core.response import success_response, error_response
from apps.warehouse.models import Goods
from django.db import models
from .models import InspectionPlan, InspectionSnapshot
from .serializers import (
    InspectionPlanListSerializer, InspectionPlanDetailSerializer,
    InspectionPlanWriteSerializer, PlanPublishSerializer, PlanWithdrawSerializer,
    InspectionSnapshotSerializer, FixSnapshotSerializer, JudgeSnapshotSerializer,
)
from . import services

logger = logging.getLogger('apps')


def first_error(errors):
    """从序列化器错误中取第一条可读信息"""
    value = errors
    while isinstance(value, dict):
        value = next(iter(value.values()))
    while isinstance(value, list):
        value = value[0]
    return str(value)


def invalid(serializer):
    return error_response(message=first_error(serializer.errors))


# ==================== 方案草案 / 发布 / 撤回 ====================

class PlanListView(APIView):
    """抽检方案列表与草案创建"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = InspectionPlan.objects.select_related(
            'category', 'created_by', 'published_by').all()

        status = request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)
        category_id = request.query_params.get('category')
        if category_id:
            queryset = queryset.filter(category_id=category_id)
        keyword = request.query_params.get('keyword')
        if keyword:
            queryset = queryset.filter(
                models.Q(code__icontains=keyword) | models.Q(name__icontains=keyword))

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        total = queryset.count()
        plans = queryset[(page - 1) * page_size:page * page_size]
        return success_response(data={
            'list': InspectionPlanListSerializer(plans, many=True).data,
            'total': total, 'page': page, 'page_size': page_size,
        })

    def post(self, request):
        serializer = InspectionPlanWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid(serializer)
        try:
            plan = services.create_draft(serializer.validated_data, user=request.user)
        except services.InspectionError as exc:
            return error_response(message=str(exc))
        logger.info('user %s created inspection plan %s', request.user.username, plan.code)
        return success_response(
            data=InspectionPlanDetailSerializer(plan).data, message='草案创建成功')


class PlanDetailView(APIView):
    """方案详情与草案更新"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        plan = InspectionPlan.objects.prefetch_related('rules', 'items').filter(pk=pk).first()
        if not plan:
            return error_response(message='方案不存在', code=404)
        return success_response(data=InspectionPlanDetailSerializer(plan).data)

    def put(self, request, pk):
        plan = InspectionPlan.objects.filter(pk=pk).first()
        if not plan:
            return error_response(message='方案不存在', code=404)
        serializer = InspectionPlanWriteSerializer(
            data=request.data, context={'instance': plan})
        if not serializer.is_valid():
            return invalid(serializer)
        try:
            plan = services.update_draft(plan, serializer.validated_data)
        except services.InspectionError as exc:
            return error_response(message=str(exc))
        return success_response(
            data=InspectionPlanDetailSerializer(plan).data, message='草案更新成功')


class PlanPublishView(APIView):
    """发布草案（固定生效区间）"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        plan = InspectionPlan.objects.filter(pk=pk).first()
        if not plan:
            return error_response(message='方案不存在', code=404)
        serializer = PlanPublishSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid(serializer)
        try:
            plan = services.publish_plan(
                plan,
                effective_from=serializer.validated_data.get('effective_from'),
                effective_to=serializer.validated_data.get('effective_to'),
                user=request.user,
            )
        except services.InspectionError as exc:
            return error_response(message=str(exc))
        logger.info('user %s published plan %s', request.user.username, plan.code)
        return success_response(
            data=InspectionPlanDetailSerializer(plan).data, message='发布成功')


class PlanWithdrawView(APIView):
    """撤回已发布方案"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        plan = InspectionPlan.objects.filter(pk=pk).first()
        if not plan:
            return error_response(message='方案不存在', code=404)
        serializer = PlanWithdrawSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid(serializer)
        try:
            plan = services.withdraw_plan(
                plan, reason=serializer.validated_data.get('reason', ''),
                user=request.user)
        except services.InspectionError as exc:
            return error_response(message=str(exc))
        logger.info('user %s withdrew plan %s', request.user.username, plan.code)
        return success_response(
            data=InspectionPlanListSerializer(plan).data, message='方案已撤回')


# ==================== 到场核验：固定快照 / 查询 / 判定 / 复检 ====================

class SnapshotFixView(APIView):
    """
    到场核验：按物资类别、来源、批量自动匹配生效方案并固定快照。
    幂等：批次已固定时直接返回原快照（旧批次查询不会套用新方案）。
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = FixSnapshotSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid(serializer)
        data = serializer.validated_data
        goods = Goods.objects.select_related(
            'variety__category').filter(pk=data['goods']).first()
        if not goods:
            return error_response(message='物资不存在', code=404)
        try:
            snapshot, created = services.fix_snapshot(
                goods=goods,
                batch_no=data['batch_no'],
                batch_quantity=data['batch_quantity'],
                source=data.get('source', ''),
                risk_level=data.get('risk_level', ''),
                severity=data.get('severity', 'auto'),
                user=request.user,
            )
        except services.NoEffectivePlanError as exc:
            return error_response(message=str(exc), code=404)
        except services.InspectionError as exc:
            return error_response(message=str(exc))
        logger.info(
            'user %s %s snapshot for goods=%s batch=%s',
            request.user.username,
            'fixed' if created else 'retrieved',
            goods.id, snapshot.batch_no,
        )
        return success_response(
            data=InspectionSnapshotSerializer(snapshot).data,
            message='快照已固定' if created else '该批次已固定，返回既有快照')


class SnapshotListView(APIView):
    """快照列表（支持按物资、批次、判定结论过滤）"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = InspectionSnapshot.objects.select_related(
            'goods', 'fixed_by', 'judged_by').all()
        goods_id = request.query_params.get('goods')
        if goods_id:
            queryset = queryset.filter(goods_id=goods_id)
        batch_no = request.query_params.get('batch_no')
        if batch_no:
            queryset = queryset.filter(batch_no=batch_no)
        result = request.query_params.get('result')
        if result:
            queryset = queryset.filter(result=result)

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        total = queryset.count()
        snapshots = queryset[(page - 1) * page_size:page * page_size]
        return success_response(data={
            'list': InspectionSnapshotSerializer(snapshots, many=True).data,
            'total': total, 'page': page, 'page_size': page_size,
        })


class SnapshotDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        snapshot = InspectionSnapshot.objects.prefetch_related('items').filter(pk=pk).first()
        if not snapshot:
            return error_response(message='快照不存在', code=404)
        return success_response(data=InspectionSnapshotSerializer(snapshot).data)


class BatchSnapshotView(APIView):
    """
    按物资 + 批次号查询当时固定的快照（含复检记录）。
    只返回固定内容，绝不重新匹配方案，保证旧批次查不到新方案。
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        goods_id = request.query_params.get('goods')
        batch_no = request.query_params.get('batch_no', '').strip()
        if not goods_id or not batch_no:
            return error_response(message='请提供物资与批次号')
        first = InspectionSnapshot.objects.prefetch_related('items').filter(
            goods_id=goods_id, batch_no=batch_no, recheck_of__isnull=True).first()
        if not first:
            return error_response(message='该批次尚未固定抽检方案快照', code=404)
        rechecks = InspectionSnapshot.objects.prefetch_related('items').filter(
            recheck_of=first).order_by('fixed_at')
        return success_response(data={
            'first': InspectionSnapshotSerializer(first).data,
            'rechecks': InspectionSnapshotSerializer(rechecks, many=True).data,
        })


class SnapshotJudgeView(APIView):
    """录入逐项检验结果并统一判定"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        snapshot = InspectionSnapshot.objects.filter(pk=pk).first()
        if not snapshot:
            return error_response(message='快照不存在', code=404)
        serializer = JudgeSnapshotSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid(serializer)
        try:
            snapshot = services.judge_snapshot(
                snapshot,
                [dict(item) for item in serializer.validated_data['items']],
                user=request.user,
                remark=serializer.validated_data.get('remark', ''),
            )
        except services.InspectionError as exc:
            return error_response(message=str(exc))
        snapshot = InspectionSnapshot.objects.prefetch_related('items').get(pk=snapshot.pk)
        return success_response(
            data=InspectionSnapshotSerializer(snapshot).data, message='判定完成')


class SnapshotRecheckView(APIView):
    """不合格后发起加严复检（沿用快照固定时的原方案/复检规则）"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        snapshot = InspectionSnapshot.objects.filter(pk=pk).first()
        if not snapshot:
            return error_response(message='快照不存在', code=404)
        try:
            recheck, created = services.start_recheck(snapshot, user=request.user)
        except services.InspectionError as exc:
            return error_response(message=str(exc))
        recheck = InspectionSnapshot.objects.prefetch_related('items').get(pk=recheck.pk)
        return success_response(
            data=InspectionSnapshotSerializer(recheck).data,
            message='复检快照已生成' if created else '该批次已存在复检快照')
