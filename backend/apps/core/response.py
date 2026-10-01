"""
统一响应格式模块
"""
from rest_framework.response import Response


class APIResponse(Response):
    """统一API响应类"""
    
    def __init__(self, data=None, message="操作成功", code=200, success=True, **kwargs):
        response_data = {
            'success': success,
            'code': code,
            'message': message,
            'data': data
        }
        super().__init__(data=response_data, status=code, **kwargs)


def success_response(data=None, message="操作成功"):
    """成功响应"""
    return APIResponse(data=data, message=message, code=200, success=True)


def error_response(message="操作失败", code=400, data=None):
    """错误响应"""
    return APIResponse(data=data, message=message, code=code, success=False)


def created_response(data=None, message="创建成功"):
    """创建成功响应"""
    return APIResponse(data=data, message=message, code=201, success=True)


def deleted_response(message="删除成功"):
    """删除成功响应"""
    return APIResponse(data=None, message=message, code=200, success=True)
