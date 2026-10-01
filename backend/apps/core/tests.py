"""
核心模块测试用例
"""
from django.test import TestCase
from rest_framework.test import APITestCase
from rest_framework import status
from .exceptions import (
    BusinessException, AuthenticationException, 
    PermissionException, NotFoundException
)
from .response import success_response, error_response, created_response, deleted_response


class ExceptionTest(TestCase):
    """异常测试"""
    
    def test_business_exception(self):
        """测试业务异常"""
        exc = BusinessException('业务错误', code=400)
        self.assertEqual(exc.message, '业务错误')
        self.assertEqual(exc.code, 400)
    
    def test_authentication_exception(self):
        """测试认证异常"""
        exc = AuthenticationException()
        self.assertEqual(exc.message, '认证失败')
        self.assertEqual(exc.code, 401)
    
    def test_permission_exception(self):
        """测试权限异常"""
        exc = PermissionException()
        self.assertEqual(exc.message, '权限不足')
        self.assertEqual(exc.code, 403)
    
    def test_not_found_exception(self):
        """测试资源不存在异常"""
        exc = NotFoundException('用户不存在')
        self.assertEqual(exc.message, '用户不存在')
        self.assertEqual(exc.code, 404)


class ResponseTest(TestCase):
    """响应测试"""
    
    def test_success_response(self):
        """测试成功响应"""
        response = success_response(data={'id': 1}, message='操作成功')
        
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['message'], '操作成功')
        self.assertEqual(response.data['data']['id'], 1)
    
    def test_error_response(self):
        """测试错误响应"""
        response = error_response(message='操作失败', code=400)
        
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['message'], '操作失败')
    
    def test_created_response(self):
        """测试创建成功响应"""
        response = created_response(data={'id': 1})
        
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['success'])
    
    def test_deleted_response(self):
        """测试删除成功响应"""
        response = deleted_response()
        
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['success'])


class LoggingConfigTest(TestCase):
    """日志配置测试"""
    
    def test_request_id(self):
        """测试请求ID"""
        from .logging_config import set_request_id, get_request_id, clear_request_id
        
        # 设置请求ID
        request_id = set_request_id()
        self.assertIsNotNone(request_id)
        self.assertEqual(len(request_id), 8)
        
        # 获取请求ID
        self.assertEqual(get_request_id(), request_id)
        
        # 清除请求ID
        clear_request_id()
        self.assertIsNone(get_request_id())
    
    def test_custom_request_id(self):
        """测试自定义请求ID"""
        from .logging_config import set_request_id, get_request_id, clear_request_id
        
        custom_id = 'test1234'
        set_request_id(custom_id)
        self.assertEqual(get_request_id(), custom_id)
        
        clear_request_id()
    
    def test_get_logger(self):
        """测试获取日志记录器"""
        from .logging_config import get_logger
        
        logger = get_logger('test')
        self.assertIsNotNone(logger)
        self.assertEqual(logger.name, 'test')
