"""
企业级日志系统配置
支持：
- 按日期轮转日志文件
- 不同级别日志分离
- JSON格式日志（便于ELK等日志系统采集）
- 请求追踪ID
- 性能监控日志
"""
import os
import logging
import json
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from functools import wraps
import time
import uuid
import threading

# 线程本地存储，用于存储请求追踪ID
_thread_local = threading.local()


def get_request_id():
    """获取当前请求的追踪ID"""
    return getattr(_thread_local, 'request_id', None)


def set_request_id(request_id=None):
    """设置当前请求的追踪ID"""
    _thread_local.request_id = request_id or str(uuid.uuid4())[:8]
    return _thread_local.request_id


def clear_request_id():
    """清除当前请求的追踪ID"""
    _thread_local.request_id = None


class JsonFormatter(logging.Formatter):
    """JSON格式日志格式化器"""
    
    def format(self, record):
        log_data = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
            'request_id': get_request_id(),
        }
        
        # 添加额外字段
        if hasattr(record, 'user_id'):
            log_data['user_id'] = record.user_id
        if hasattr(record, 'username'):
            log_data['username'] = record.username
        if hasattr(record, 'ip_address'):
            log_data['ip_address'] = record.ip_address
        if hasattr(record, 'method'):
            log_data['method'] = record.method
        if hasattr(record, 'path'):
            log_data['path'] = record.path
        if hasattr(record, 'status_code'):
            log_data['status_code'] = record.status_code
        if hasattr(record, 'duration_ms'):
            log_data['duration_ms'] = record.duration_ms
        if hasattr(record, 'extra_data'):
            log_data['extra_data'] = record.extra_data
        
        # 添加异常信息
        if record.exc_info:
            log_data['exception'] = {
                'type': record.exc_info[0].__name__ if record.exc_info[0] else None,
                'message': str(record.exc_info[1]) if record.exc_info[1] else None,
                'traceback': traceback.format_exception(*record.exc_info) if record.exc_info[0] else None
            }
        
        return json.dumps(log_data, ensure_ascii=False)


class ColoredFormatter(logging.Formatter):
    """带颜色的控制台日志格式化器"""
    
    COLORS = {
        'DEBUG': '\033[36m',     # 青色
        'INFO': '\033[32m',      # 绿色
        'WARNING': '\033[33m',   # 黄色
        'ERROR': '\033[31m',     # 红色
        'CRITICAL': '\033[35m',  # 紫色
    }
    RESET = '\033[0m'
    
    def format(self, record):
        color = self.COLORS.get(record.levelname, self.RESET)
        request_id = get_request_id()
        request_id_str = f'[{request_id}]' if request_id else ''
        
        # 格式化时间
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 构建日志消息
        message = f"{color}{timestamp} {record.levelname:8s}{self.RESET} {request_id_str} [{record.name}] {record.getMessage()}"
        
        if record.exc_info:
            message += '\n' + ''.join(traceback.format_exception(*record.exc_info))
        
        return message


class LoggerAdapter(logging.LoggerAdapter):
    """日志适配器，支持添加额外上下文"""
    
    def process(self, msg, kwargs):
        extra = kwargs.get('extra', {})
        extra['request_id'] = get_request_id()
        kwargs['extra'] = extra
        return msg, kwargs


def setup_logging(base_dir, debug=False):
    """
    配置企业级日志系统
    
    Args:
        base_dir: 日志文件基础目录
        debug: 是否为调试模式
    """
    logs_dir = os.path.join(base_dir, 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    
    # 日志级别
    log_level = logging.DEBUG if debug else logging.INFO
    
    # 根日志配置
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # 清除现有处理器
    root_logger.handlers.clear()
    
    # 1. 控制台处理器（带颜色）
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(ColoredFormatter())
    root_logger.addHandler(console_handler)
    
    # 2. 应用日志文件（按日期轮转）
    app_handler = TimedRotatingFileHandler(
        filename=os.path.join(logs_dir, 'app.log'),
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)-8s [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    root_logger.addHandler(app_handler)
    
    # 3. 错误日志文件（单独记录ERROR及以上级别）
    error_handler = TimedRotatingFileHandler(
        filename=os.path.join(logs_dir, 'error.log'),
        when='midnight',
        interval=1,
        backupCount=90,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)-8s [%(name)s] [%(module)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    root_logger.addHandler(error_handler)
    
    # 4. JSON格式日志（便于日志采集系统）
    json_handler = TimedRotatingFileHandler(
        filename=os.path.join(logs_dir, 'app.json.log'),
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    json_handler.setLevel(logging.INFO)
    json_handler.setFormatter(JsonFormatter())
    root_logger.addHandler(json_handler)
    
    # 5. 访问日志（记录所有HTTP请求）
    access_logger = logging.getLogger('access')
    access_logger.setLevel(logging.INFO)
    access_logger.propagate = False
    
    access_handler = TimedRotatingFileHandler(
        filename=os.path.join(logs_dir, 'access.log'),
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    access_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    access_logger.addHandler(access_handler)
    
    # 6. 性能日志（记录慢请求）
    perf_logger = logging.getLogger('performance')
    perf_logger.setLevel(logging.INFO)
    perf_logger.propagate = False
    
    perf_handler = TimedRotatingFileHandler(
        filename=os.path.join(logs_dir, 'performance.log'),
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    perf_handler.setFormatter(JsonFormatter())
    perf_logger.addHandler(perf_handler)
    
    # 7. 安全日志（记录登录、权限等安全相关事件）
    security_logger = logging.getLogger('security')
    security_logger.setLevel(logging.INFO)
    security_logger.propagate = False
    
    security_handler = TimedRotatingFileHandler(
        filename=os.path.join(logs_dir, 'security.log'),
        when='midnight',
        interval=1,
        backupCount=90,
        encoding='utf-8'
    )
    security_handler.setFormatter(JsonFormatter())
    security_logger.addHandler(security_handler)
    
    return root_logger


def get_logger(name):
    """获取日志记录器"""
    return logging.getLogger(name)


def log_function_call(logger=None, log_args=True, log_result=False):
    """
    函数调用日志装饰器
    
    Args:
        logger: 日志记录器
        log_args: 是否记录参数
        log_result: 是否记录返回值
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            _logger = logger or logging.getLogger(func.__module__)
            func_name = f"{func.__module__}.{func.__name__}"
            
            # 记录函数调用
            if log_args:
                _logger.debug(f"Calling {func_name} with args={args}, kwargs={kwargs}")
            else:
                _logger.debug(f"Calling {func_name}")
            
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = (time.time() - start_time) * 1000
                
                if log_result:
                    _logger.debug(f"{func_name} returned {result} in {duration:.2f}ms")
                else:
                    _logger.debug(f"{func_name} completed in {duration:.2f}ms")
                
                return result
            except Exception as e:
                duration = (time.time() - start_time) * 1000
                _logger.error(f"{func_name} failed after {duration:.2f}ms: {e}", exc_info=True)
                raise
        
        return wrapper
    return decorator


def log_performance(threshold_ms=1000):
    """
    性能监控装饰器
    
    Args:
        threshold_ms: 慢请求阈值（毫秒）
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            perf_logger = logging.getLogger('performance')
            func_name = f"{func.__module__}.{func.__name__}"
            
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration_ms = (time.time() - start_time) * 1000
                
                if duration_ms >= threshold_ms:
                    perf_logger.warning(
                        f"Slow function detected",
                        extra={
                            'extra_data': {
                                'function': func_name,
                                'duration_ms': round(duration_ms, 2),
                                'threshold_ms': threshold_ms
                            }
                        }
                    )
        
        return wrapper
    return decorator
