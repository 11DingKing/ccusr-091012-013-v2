"""
抽检管理视图
"""
import logging

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.core.exceptions import BusinessException
from apps.core.response import success_response, error_response
from apps.warehouse.models import Category
from .models import Inspection, SamplingPlan
from .serializers import (
    InspectionCompleteSerializer, InspectionFixSerializer, InspectionSerializer,
    SamplingPlanCreateSerializer, SamplingPlanSerializer,
)
from .services import (
    check_plan_publishable, complete_inspection, fix_inspection,
)

logger = logging.getLogger('apps')


def _first_error(errors):
    """取序列化器的第一条错误信息"""
    first = list(errors.values())[0]
    if isinstance(first, (list, tuple)):
        first = first[0]
    return str(first)


def _paginate(request, queryset):
    """按 page/page_size 参数分页"""
    page = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 10))
    start = (page - 1) * page_size
    end = start + page_size
    return {
        'list': queryset[start:end],
        'total': queryset.count(),
        'page': page,
        'page_size': page_size,
    }


# ==================== 抽检方案管理 ====================

class SamplingPlanListView(APIView):
    """抽检方案列表视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = SamplingPlan.objects.all().order_by('-created_at')
        status = request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)
        category_id = request.query_params.get('category_id')
        if category_id:
            queryset = queryset.filter(category_id=category_id)

        page_data = _paginate(request, queryset)
        page_data['list'] = SamplingPlanSerializer(page_data['list'], many=True).data
        return success_response(data=page_data)

    def post(self, request):
        """创建抽检方案（草案）"""
        serializer = SamplingPlanCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))

        data = serializer.validated_data
        plan = SamplingPlan.objects.create(
            name=data['name'],
            category=Category.objects.get(pk=data['category']),
            source=data['source'],
            min_quantity=data['min_quantity'],
            max_quantity=data['max_quantity'],
            sample_ratio=data['sample_ratio'],
            tightened_ratio=data['tightened_ratio'],
            min_sample_size=data['min_sample_size'],
            max_sample_size=data['max_sample_size'],
            check_items=data['check_items'],
            priority=data['priority'],
            effective_from=data['effective_from'],
            effective_to=data['effective_to'],
            created_by=request.user,
        )

        logger.info(f"User {request.user.username} created sampling plan {plan.name}")

        return success_response(data=SamplingPlanSerializer(plan).data, message='创建成功')


class SamplingPlanDetailView(APIView):
    """抽检方案详情视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            plan = SamplingPlan.objects.get(pk=pk)
        except SamplingPlan.DoesNotExist:
            return error_response(message='抽检方案不存在', code=404)
        return success_response(data=SamplingPlanSerializer(plan).data)

    def put(self, request, pk):
        """更新抽检方案（仅草案可编辑）"""
        try:
            plan = SamplingPlan.objects.get(pk=pk)
        except SamplingPlan.DoesNotExist:
            return error_response(message='抽检方案不存在', code=404)

        if not plan.is_editable:
            return error_response(message='仅草案状态的方案可以编辑')

        serializer = SamplingPlanCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))

        data = serializer.validated_data
        plan.name = data['name']
        plan.category = Category.objects.get(pk=data['category'])
        plan.source = data['source']
        plan.min_quantity = data['min_quantity']
        plan.max_quantity = data['max_quantity']
        plan.sample_ratio = data['sample_ratio']
        plan.tightened_ratio = data['tightened_ratio']
        plan.min_sample_size = data['min_sample_size']
        plan.max_sample_size = data['max_sample_size']
        plan.check_items = data['check_items']
        plan.priority = data['priority']
        plan.effective_from = data['effective_from']
        plan.effective_to = data['effective_to']
        plan.save()

        logger.info(f"User {request.user.username} updated sampling plan {plan.name}")

        return success_response(data=SamplingPlanSerializer(plan).data, message='更新成功')

    def delete(self, request, pk):
        """删除抽检方案（仅草案可删除，已发布方案只能撤回以保留审计轨迹）"""
        try:
            plan = SamplingPlan.objects.get(pk=pk)
        except SamplingPlan.DoesNotExist:
            return error_response(message='抽检方案不存在', code=404)

        if not plan.is_editable:
            return error_response(message='仅草案状态的方案可以删除')

        name = plan.name
        plan.delete()

        logger.info(f"User {request.user.username} deleted sampling plan {name}")

        return success_response(message='删除成功')


class SamplingPlanPublishView(APIView):
    """抽检方案发布视图"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            plan = SamplingPlan.objects.get(pk=pk)
        except SamplingPlan.DoesNotExist:
            return error_response(message='抽检方案不存在', code=404)

        if plan.status == 'published':
            return error_response(message='方案已发布，请勿重复操作')
        if plan.status == 'withdrawn':
            return error_response(message='方案已撤回，不能重新发布')

        try:
            check_plan_publishable(plan)
        except BusinessException as exc:
            return error_response(message=exc.message)

        plan.status = 'published'
        plan.published_at = timezone.now()
        plan.published_by = request.user
        plan.save()

        logger.info(f"User {request.user.username} published sampling plan {plan.name}")

        return success_response(data=SamplingPlanSerializer(plan).data, message='发布成功')


class SamplingPlanWithdrawView(APIView):
    """抽检方案撤回视图（撤回后立即不再参与匹配，已固定快照不受影响）"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            plan = SamplingPlan.objects.get(pk=pk)
        except SamplingPlan.DoesNotExist:
            return error_response(message='抽检方案不存在', code=404)

        if plan.status != 'published':
            return error_response(message='仅已发布的方案可以撤回')

        reason = str(request.data.get('reason', '')).strip()
        if not reason:
            return error_response(message='请填写撤回原因')
        if len(reason) > 200:
            return error_response(message='撤回原因最多200个字')

        plan.status = 'withdrawn'
        plan.withdrawn_at = timezone.now()
        plan.withdrawn_by = request.user
        plan.withdraw_reason = reason
        plan.save()

        logger.info(f"User {request.user.username} withdrew sampling plan {plan.name}")

        return success_response(data=SamplingPlanSerializer(plan).data, message='撤回成功')


# ==================== 到场核验 ====================

class InspectionListView(APIView):
    """到场核验列表视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Inspection.objects.all().order_by('-created_at')
        batch_no = request.query_params.get('batch_no')
        if batch_no:
            queryset = queryset.filter(batch_no=batch_no)
        category_id = request.query_params.get('category_id')
        if category_id:
            queryset = queryset.filter(category_id=category_id)
        status = request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)
        conclusion = request.query_params.get('conclusion')
        if conclusion:
            queryset = queryset.filter(conclusion=conclusion)

        page_data = _paginate(request, queryset)
        page_data['list'] = InspectionSerializer(page_data['list'], many=True).data
        return success_response(data=page_data)


class InspectionFixView(APIView):
    """到场核验固定方案快照视图

    按物资品类、来源和批量自动匹配已发布方案并冻结快照；
    同一批次号重复核验返回原快照，不套用新方案。
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = InspectionFixSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))

        data = serializer.validated_data
        category = Category.objects.get(pk=data['category'])
        try:
            inspection, created = fix_inspection(
                batch_no=data['batch_no'],
                category=category,
                source=data['source'],
                batch_quantity=data['batch_quantity'],
                verified_by=request.user,
                verified_at=data['verified_at'],
            )
        except BusinessException as exc:
            return error_response(message=exc.message, code=exc.code)

        if created:
            logger.info(
                f"User {request.user.username} fixed inspection for batch "
                f"{inspection.batch_no} with plan {inspection.plan_snapshot.get('plan_name')}"
            )

        message = '方案快照已固定' if created else '批次已存在，返回原方案快照'
        return success_response(data=InspectionSerializer(inspection).data, message=message)


class InspectionDetailView(APIView):
    """到场核验详情视图（返回固定时刻的快照内容）"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            inspection = Inspection.objects.get(pk=pk)
        except Inspection.DoesNotExist:
            return error_response(message='核验记录不存在', code=404)
        return success_response(data=InspectionSerializer(inspection).data)


class InspectionCompleteView(APIView):
    """核验判定视图（录入检查项结果，系统推导判定结论）"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            inspection = Inspection.objects.get(pk=pk)
        except Inspection.DoesNotExist:
            return error_response(message='核验记录不存在', code=404)

        serializer = InspectionCompleteSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))

        try:
            complete_inspection(
                inspection,
                item_results=serializer.validated_data['item_results'],
                remark=serializer.validated_data['remark'],
            )
        except BusinessException as exc:
            return error_response(message=exc.message, code=exc.code)

        logger.info(
            f"User {request.user.username} completed inspection "
            f"{inspection.batch_no}: {inspection.conclusion}"
        )

        return success_response(data=InspectionSerializer(inspection).data, message='判定成功')
