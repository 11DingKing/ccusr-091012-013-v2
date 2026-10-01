"""监管物资保管服务的 ASGI 应用入口。"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'warehouse_system.settings')

application = get_asgi_application()
