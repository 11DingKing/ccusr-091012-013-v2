"""
认证模块测试用例
"""
import json
from django.test import TestCase, Client
from django.urls import reverse
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from .models import User, OperationLog
from .backends import generate_token, decode_token


class UserModelTest(TestCase):
    """用户模型测试"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            real_name='测试用户',
            role='operator'
        )
    
    def test_create_user(self):
        """测试创建普通用户"""
        self.assertEqual(self.user.username, 'testuser')
        self.assertEqual(self.user.real_name, '测试用户')
        self.assertEqual(self.user.role, 'operator')
        self.assertTrue(self.user.is_active)
        self.assertFalse(self.user.is_staff)
    
    def test_create_superuser(self):
        """测试创建超级用户"""
        admin = User.objects.create_superuser(
            username='admin',
            password='admin123'
        )
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)
        self.assertEqual(admin.role, 'superadmin')
    
    def test_user_password(self):
        """测试密码验证"""
        self.assertTrue(self.user.check_password('testpass123'))
        self.assertFalse(self.user.check_password('wrongpassword'))
    
    def test_user_str(self):
        """测试用户字符串表示"""
        self.assertEqual(str(self.user), 'testuser')


class JWTTokenTest(TestCase):
    """JWT Token测试"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create_user(
            username='tokenuser',
            password='tokenpass123'
        )
    
    def test_generate_token(self):
        """测试生成Token"""
        token = generate_token(self.user)
        self.assertIsNotNone(token)
        self.assertIsInstance(token, str)
    
    def test_decode_token(self):
        """测试解码Token"""
        token = generate_token(self.user)
        payload = decode_token(token)
        
        self.assertIsNotNone(payload)
        self.assertEqual(payload['user_id'], self.user.id)
        self.assertEqual(payload['username'], self.user.username)
    
    def test_decode_invalid_token(self):
        """测试解码无效Token"""
        payload = decode_token('invalid_token')
        self.assertIsNone(payload)


class LoginAPITest(APITestCase):
    """登录API测试"""
    
    def setUp(self):
        """测试前准备"""
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='loginuser',
            password='loginpass123',
            real_name='登录测试用户'
        )
        self.login_url = '/api/auth/login/'
    
    def test_login_success(self):
        """测试登录成功"""
        response = self.client.post(self.login_url, {
            'username': 'loginuser',
            'password': 'loginpass123'
        }, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('token', data['data'])
        self.assertIn('user', data['data'])
        self.assertEqual(data['data']['user']['username'], 'loginuser')
    
    def test_login_wrong_password(self):
        """测试密码错误"""
        response = self.client.post(self.login_url, {
            'username': 'loginuser',
            'password': 'wrongpassword'
        }, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        data = response.json()
        self.assertFalse(data['success'])
    
    def test_login_user_not_found(self):
        """测试用户不存在"""
        response = self.client.post(self.login_url, {
            'username': 'nonexistent',
            'password': 'somepassword'
        }, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_login_missing_fields(self):
        """测试缺少字段"""
        response = self.client.post(self.login_url, {
            'username': 'loginuser'
        }, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_login_inactive_user(self):
        """测试禁用用户登录"""
        self.user.is_active = False
        self.user.save()
        
        response = self.client.post(self.login_url, {
            'username': 'loginuser',
            'password': 'loginpass123'
        }, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class LogoutAPITest(APITestCase):
    """退出登录API测试"""
    
    def setUp(self):
        """测试前准备"""
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='logoutuser',
            password='logoutpass123'
        )
        self.token = generate_token(self.user)
        self.logout_url = '/api/auth/logout/'
    
    def test_logout_success(self):
        """测试退出成功"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')
        response = self.client.post(self.logout_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data['success'])
    
    def test_logout_without_token(self):
        """测试未登录退出"""
        response = self.client.post(self.logout_url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class UserInfoAPITest(APITestCase):
    """用户信息API测试"""
    
    def setUp(self):
        """测试前准备"""
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='infouser',
            password='infopass123',
            real_name='信息测试用户',
            role='admin'
        )
        self.token = generate_token(self.user)
        self.user_info_url = '/api/auth/user/'
    
    def test_get_user_info(self):
        """测试获取用户信息"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')
        response = self.client.get(self.user_info_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['data']['username'], 'infouser')
        self.assertEqual(data['data']['real_name'], '信息测试用户')
    
    def test_get_user_info_without_token(self):
        """测试未登录获取用户信息"""
        response = self.client.get(self.user_info_url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class OperationLogTest(TestCase):
    """操作日志测试"""
    
    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create_user(
            username='loguser',
            password='logpass123'
        )
    
    def test_create_operation_log(self):
        """测试创建操作日志"""
        log = OperationLog.objects.create(
            user=self.user,
            action='login',
            module='认证管理',
            detail='用户登录',
            ip_address='127.0.0.1'
        )
        
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.action, 'login')
        self.assertEqual(log.module, '认证管理')
    
    def test_operation_log_str(self):
        """测试操作日志字符串表示"""
        log = OperationLog.objects.create(
            user=self.user,
            action='create',
            module='货物管理'
        )
        
        self.assertIn('loguser', str(log))
        self.assertIn('create', str(log))
