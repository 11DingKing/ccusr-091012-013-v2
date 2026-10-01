"""
认证URL配置
"""
from django.urls import path
from .views import (
    LoginView, LogoutView, UserInfoView, 
    UserListView, UserDetailView, OperationLogListView
)

urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('user/', UserInfoView.as_view(), name='user-info'),
    path('users/', UserListView.as_view(), name='user-list'),
    path('users/<int:pk>/', UserDetailView.as_view(), name='user-detail'),
    path('logs/', OperationLogListView.as_view(), name='operation-logs'),
]
