"""
人员管理视图
"""
import logging
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from apps.core.response import success_response, error_response
from apps.authentication.models import User
from .models import StockOutPerson
from .serializers import (
    StockOutPersonSerializer, StockOutPersonCreateSerializer, AdminUserSerializer
)

logger = logging.getLogger('apps')


class StockOutPersonListView(APIView):
    """出库人员列表视图"""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    
    def get(self, request):
        queryset = StockOutPerson.objects.all().order_by('-created_at')
        
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        start = (page - 1) * page_size
        end = start + page_size
        
        total = queryset.count()
        persons = queryset[start:end]
        
        serializer = StockOutPersonSerializer(persons, many=True)
        
        return success_response(data={
            'list': serializer.data,
            'total': total,
            'page': page,
            'page_size': page_size
        })
    
    def post(self, request):
        """创建出库人员"""
        serializer = StockOutPersonCreateSerializer(data=request.data)
        if not serializer.is_valid():
            errors = serializer.errors
            first_error = list(errors.values())[0][0]
            return error_response(message=str(first_error))
        
        data = serializer.validated_data
        binduser = None
        if data.get('binduser'):
            try:
                binduser = User.objects.get(pk=data['binduser'])
            except User.DoesNotExist:
                pass
        
        person = StockOutPerson.objects.create(
            police_no=data['police_no'],
            name=data['name'],
            id_card=data.get('id_card', ''),
            phone=data['phone'],
            binduser=binduser
        )
        
        # 处理头像上传
        if 'avatar' in request.FILES:
            person.avatar = request.FILES['avatar']
            person.save()
        
        logger.info(f"User {request.user.username} created stock out person {person.name}")
        
        return success_response(data=StockOutPersonSerializer(person).data, message='创建成功')


class StockOutPersonDetailView(APIView):
    """出库人员详情视图"""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    
    def get(self, request, pk):
        try:
            person = StockOutPerson.objects.get(pk=pk)
        except StockOutPerson.DoesNotExist:
            return error_response(message='出库人员不存在', code=404)
        
        serializer = StockOutPersonSerializer(person)
        return success_response(data=serializer.data)
    
    def put(self, request, pk):
        """更新出库人员"""
        try:
            person = StockOutPerson.objects.get(pk=pk)
        except StockOutPerson.DoesNotExist:
            return error_response(message='出库人员不存在', code=404)
        
        serializer = StockOutPersonCreateSerializer(
            data=request.data, 
            context={'instance': person}
        )
        if not serializer.is_valid():
            errors = serializer.errors
            first_error = list(errors.values())[0][0]
            return error_response(message=str(first_error))
        
        data = serializer.validated_data
        person.police_no = data['police_no']
        person.name = data['name']
        person.id_card = data.get('id_card', '')
        person.phone = data['phone']
        
        if data.get('binduser'):
            try:
                person.binduser = User.objects.get(pk=data['binduser'])
            except User.DoesNotExist:
                person.binduser = None
        else:
            person.binduser = None
        
        # 处理头像上传
        if 'avatar' in request.FILES:
            person.avatar = request.FILES['avatar']
        
        person.save()
        
        logger.info(f"User {request.user.username} updated stock out person {person.name}")
        
        return success_response(data=StockOutPersonSerializer(person).data, message='更新成功')
    
    def delete(self, request, pk):
        """删除出库人员"""
        try:
            person = StockOutPerson.objects.get(pk=pk)
        except StockOutPerson.DoesNotExist:
            return error_response(message='出库人员不存在', code=404)
        
        name = person.name
        person.delete()
        
        logger.info(f"User {request.user.username} deleted stock out person {name}")
        
        return success_response(message='删除成功')


class AdminUserListView(APIView):
    """管理员用户列表（用于下拉选择）"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        # 只获取管理员用户（不包括超级管理员和普通用户）
        users = User.objects.filter(role='admin', is_active=True)
        serializer = AdminUserSerializer(users, many=True)
        return success_response(data=serializer.data)
