"""
认证视图
"""
import logging
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from apps.core.response import success_response, error_response
from .models import User, OperationLog
from .serializers import LoginSerializer, UserSerializer, OperationLogSerializer, UserCreateSerializer
from .backends import generate_token
from .filters import OperationLogFilter

logger = logging.getLogger('apps')


class LoginView(APIView):
    """登录视图"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            errors = serializer.errors
            first_error = list(errors.values())[0][0]
            return error_response(message=str(first_error))
        
        username = serializer.validated_data['username']
        password = serializer.validated_data['password']
        
        user = User.objects.filter(username=username).first()
        if not user:
            logger.warning(f"Login failed: user {username} not found")
            return error_response(message='用户名或密码错误', code=401)
        
        if not user.check_password(password):
            logger.warning(f"Login failed: wrong password for user {username}")
            return error_response(message='用户名或密码错误', code=401)
        
        if not user.is_active:
            logger.warning(f"Login failed: user {username} is disabled")
            return error_response(message='账号已被禁用', code=401)
        
        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])
        
        token = generate_token(user)
        
        logger.info(f"User {username} logged in successfully")
        
        return success_response(data={
            'token': token,
            'user': UserSerializer(user).data
        }, message='登录成功')


class LogoutView(APIView):
    """退出登录视图"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        logger.info(f"User {request.user.username} logged out")
        return success_response(message='退出成功')


class UserInfoView(APIView):
    """获取当前用户信息"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        serializer = UserSerializer(request.user)
        return success_response(data=serializer.data)


class UserListView(APIView):
    """用户列表视图 - 考勤人员管理"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        # 只有管理员可以访问
        if not request.user.is_admin:
            return error_response(message='无权限访问', code=403)
        
        queryset = User.objects.all().order_by('-created_at')
        
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        start = (page - 1) * page_size
        end = start + page_size
        
        total = queryset.count()
        users = queryset[start:end]
        
        serializer = UserSerializer(users, many=True)
        
        return success_response(data={
            'list': serializer.data,
            'total': total,
            'page': page,
            'page_size': page_size
        })
    
    def post(self, request):
        """创建用户"""
        if not request.user.is_admin:
            return error_response(message='无权限操作', code=403)
        
        serializer = UserCreateSerializer(data=request.data)
        if not serializer.is_valid():
            errors = serializer.errors
            first_error = list(errors.values())[0][0]
            return error_response(message=str(first_error))
        
        username = serializer.validated_data['username']
        password = serializer.validated_data['password']
        role = serializer.validated_data.get('role', 'user')
        
        if User.objects.filter(username=username).exists():
            return error_response(message='用户名已存在')
        
        user = User.objects.create_user(
            username=username,
            password=password,
            role=role
        )
        
        logger.info(f"User {request.user.username} created user {username}")
        
        return success_response(data=UserSerializer(user).data, message='创建成功')


class UserDetailView(APIView):
    """用户详情视图"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, pk):
        if not request.user.is_admin:
            return error_response(message='无权限访问', code=403)
        
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return error_response(message='用户不存在', code=404)
        
        serializer = UserSerializer(user)
        return success_response(data=serializer.data)
    
    def put(self, request, pk):
        """更新用户"""
        if not request.user.is_admin:
            return error_response(message='无权限操作', code=403)
        
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return error_response(message='用户不存在', code=404)
        
        username = request.data.get('username')
        password = request.data.get('password')
        role = request.data.get('role')
        
        if username and username != user.username:
            if User.objects.filter(username=username).exclude(pk=pk).exists():
                return error_response(message='用户名已存在')
            user.username = username
        
        if password:
            user.set_password(password)
        
        if role and not user.is_super_admin:
            user.role = role
        
        user.save()
        
        logger.info(f"User {request.user.username} updated user {user.username}")
        
        return success_response(data=UserSerializer(user).data, message='更新成功')
    
    def delete(self, request, pk):
        """删除用户"""
        if not request.user.is_admin:
            return error_response(message='无权限操作', code=403)
        
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return error_response(message='用户不存在', code=404)
        
        # 超级管理员（ID=1）不能被删除
        if user.is_super_admin:
            return error_response(message='超级管理员不能被删除')
        
        username = user.username
        user.delete()
        
        logger.info(f"User {request.user.username} deleted user {username}")
        
        return success_response(message='删除成功')


class OperationLogListView(APIView):
    """操作日志列表"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        queryset = OperationLog.objects.all()
        
        filterset = OperationLogFilter(request.query_params, queryset=queryset)
        queryset = filterset.qs
        
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        start = (page - 1) * page_size
        end = start + page_size
        
        total = queryset.count()
        logs = queryset[start:end]
        
        serializer = OperationLogSerializer(logs, many=True)
        
        return success_response(data={
            'list': serializer.data,
            'total': total,
            'page': page,
            'page_size': page_size
        })
