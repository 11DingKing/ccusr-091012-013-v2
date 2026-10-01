"""监管物资保管服务的 WSGI 应用入口。"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'warehouse_system.settings')

application = get_wsgi_application()
