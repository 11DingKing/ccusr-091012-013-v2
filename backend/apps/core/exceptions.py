"""
全局异常处理模块
"""
import logging
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404

logger = logging.getLogger('apps')


class BusinessException(Exception):
    """业务异常基类"""
    def __init__(self, message, code=400):
        self.message = message
        self.code = code
        super().__init__(message)


class AuthenticationException(BusinessException):
    """认证异常"""
    def __init__(self, message="认证失败"):
        super().__init__(message, code=401)


class PermissionException(BusinessException):
    """权限异常"""
    def __init__(self, message="权限不足"):
        super().__init__(message, code=403)


class NotFoundException(BusinessException):
    """资源不存在异常"""
    def __init__(self, message="资源不存在"):
        super().__init__(message, code=404)


def custom_exception_handler(exc, context):
    """
    自定义异常处理器
    """
    # 记录异常日志
    logger.error(f"Exception occurred: {exc}", exc_info=True)
    
    # 处理业务异常
    if isinstance(exc, BusinessException):
        return Response({
            'success': False,
            'code': exc.code,
            'message': exc.message,
            'data': None
        }, status=exc.code)
    
    # 处理Django验证异常
    if isinstance(exc, DjangoValidationError):
        return Response({
            'success': False,
            'code': 400,
            'message': str(exc.message) if hasattr(exc, 'message') else str(exc),
            'data': None
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # 处理404异常
    if isinstance(exc, Http404):
        return Response({
            'success': False,
            'code': 404,
            'message': '资源不存在',
            'data': None
        }, status=status.HTTP_404_NOT_FOUND)
    
    # 调用默认的异常处理
    response = exception_handler(exc, context)
    
    if response is not None:
        # 统一响应格式
        custom_response_data = {
            'success': False,
            'code': response.status_code,
            'message': response.data.get('detail', '请求失败') if isinstance(response.data, dict) else str(response.data),
            'data': None
        }
        response.data = custom_response_data
        return response
    
    # 处理未捕获的异常
    return Response({
        'success': False,
        'code': 500,
        'message': '服务器内部错误',
        'data': None
    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
