"""
日志中间件
记录所有HTTP请求和响应
"""
import time
import logging
from django.utils.deprecation import MiddlewareMixin
from .logging_config import set_request_id, clear_request_id, get_request_id

logger = logging.getLogger('apps')
access_logger = logging.getLogger('access')
perf_logger = logging.getLogger('performance')
security_logger = logging.getLogger('security')


class RequestLoggingMiddleware(MiddlewareMixin):
    """请求日志中间件"""
    
    # 慢请求阈值（毫秒）
    SLOW_REQUEST_THRESHOLD = 1000
    
    # 不记录的路径前缀
    EXCLUDE_PATHS = [
        '/static/',
        '/media/',
        '/favicon.ico',
    ]
    
    def process_request(self, request):
        """请求开始时"""
        # 生成请求追踪ID
        request_id = set_request_id()
        request.request_id = request_id
        
        # 记录请求开始时间
        request.start_time = time.time()
        
        # 获取客户端IP
        request.client_ip = self._get_client_ip(request)
    
    def process_response(self, request, response):
        """请求结束时"""
        try:
            # 检查是否需要记录
            if self._should_skip(request):
                return response
            
            # 计算请求耗时
            duration_ms = 0
            if hasattr(request, 'start_time'):
                duration_ms = (time.time() - request.start_time) * 1000
            
            # 获取用户信息
            user_id = None
            username = None
            if hasattr(request, 'user') and request.user.is_authenticated:
                user_id = request.user.id
                username = request.user.username
            
            # 记录访问日志
            log_message = (
                f'{request.client_ip} '
                f'{request.method} {request.path} '
                f'{response.status_code} '
                f'{duration_ms:.2f}ms '
                f'[{get_request_id()}] '
                f'user={username or "-"}'
            )
            access_logger.info(log_message)
            
            # 记录详细日志
            logger.info(
                f"Request completed: {request.method} {request.path}",
                extra={
                    'user_id': user_id,
                    'username': username,
                    'ip_address': request.client_ip,
                    'method': request.method,
                    'path': request.path,
                    'status_code': response.status_code,
                    'duration_ms': round(duration_ms, 2),
                }
            )
            
            # 记录慢请求
            if duration_ms >= self.SLOW_REQUEST_THRESHOLD:
                perf_logger.warning(
                    f"Slow request detected",
                    extra={
                        'user_id': user_id,
                        'username': username,
                        'ip_address': request.client_ip,
                        'method': request.method,
                        'path': request.path,
                        'status_code': response.status_code,
                        'duration_ms': round(duration_ms, 2),
                        'extra_data': {
                            'query_string': request.META.get('QUERY_STRING', ''),
                            'user_agent': request.META.get('HTTP_USER_AGENT', '')[:200],
                        }
                    }
                )
            
            # 添加请求ID到响应头
            response['X-Request-ID'] = get_request_id()
            
        except Exception as e:
            logger.error(f"Error in request logging: {e}", exc_info=True)
        finally:
            # 清除请求追踪ID
            clear_request_id()
        
        return response
    
    def process_exception(self, request, exception):
        """处理异常"""
        duration_ms = 0
        if hasattr(request, 'start_time'):
            duration_ms = (time.time() - request.start_time) * 1000
        
        user_id = None
        username = None
        if hasattr(request, 'user') and request.user.is_authenticated:
            user_id = request.user.id
            username = request.user.username
        
        logger.error(
            f"Request exception: {request.method} {request.path} - {exception}",
            exc_info=True,
            extra={
                'user_id': user_id,
                'username': username,
                'ip_address': getattr(request, 'client_ip', None),
                'method': request.method,
                'path': request.path,
                'duration_ms': round(duration_ms, 2),
            }
        )
        
        return None
    
    def _get_client_ip(self, request):
        """获取客户端IP"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', '')
        return ip
    
    def _should_skip(self, request):
        """检查是否跳过日志记录"""
        path = request.path
        for prefix in self.EXCLUDE_PATHS:
            if path.startswith(prefix):
                return True
        return False


class SecurityLoggingMiddleware(MiddlewareMixin):
    """安全日志中间件"""
    
    # 需要记录的安全相关路径
    SECURITY_PATHS = [
        '/api/auth/login/',
        '/api/auth/logout/',
    ]
    
    def process_response(self, request, response):
        """记录安全相关事件"""
        path = request.path
        
        # 检查是否是安全相关路径
        if path not in self.SECURITY_PATHS:
            return response
        
        client_ip = self._get_client_ip(request)
        
        # 登录事件
        if path == '/api/auth/login/':
            if response.status_code == 200:
                # 登录成功
                security_logger.info(
                    "Login success",
                    extra={
                        'ip_address': client_ip,
                        'path': path,
                        'status_code': response.status_code,
                        'extra_data': {
                            'event_type': 'login_success',
                            'user_agent': request.META.get('HTTP_USER_AGENT', '')[:200],
                        }
                    }
                )
            else:
                # 登录失败
                security_logger.warning(
                    "Login failed",
                    extra={
                        'ip_address': client_ip,
                        'path': path,
                        'status_code': response.status_code,
                        'extra_data': {
                            'event_type': 'login_failed',
                            'user_agent': request.META.get('HTTP_USER_AGENT', '')[:200],
                        }
                    }
                )
        
        # 退出事件
        elif path == '/api/auth/logout/':
            user_id = None
            username = None
            if hasattr(request, 'user') and request.user.is_authenticated:
                user_id = request.user.id
                username = request.user.username
            
            security_logger.info(
                "Logout",
                extra={
                    'user_id': user_id,
                    'username': username,
                    'ip_address': client_ip,
                    'path': path,
                    'extra_data': {
                        'event_type': 'logout',
                    }
                }
            )
        
        return response
    
    def _get_client_ip(self, request):
        """获取客户端IP"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', '')
        return ip
