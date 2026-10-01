"""
Pytest配置文件
"""
import os
import django
from django.conf import settings

# 设置Django配置
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'warehouse_system.settings')


def pytest_configure():
    """Pytest配置"""
    settings.DEBUG = False
    django.setup()
