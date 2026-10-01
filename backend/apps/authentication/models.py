"""
用户认证模型
"""
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin


# 超级管理员固定ID
SUPERADMIN_ID = 1


class UserManager(BaseUserManager):
    """用户管理器"""
    
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError('用户名不能为空')
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('role', 'superadmin')
        
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db, force_insert=True)
        return user


class User(AbstractBaseUser, PermissionsMixin):
    """用户模型"""
    
    ROLE_CHOICES = [
        ('superadmin', '超级管理员'),
        ('admin', '管理员'),
        ('user', '普通用户'),
    ]
    
    username = models.CharField('用户名', max_length=50, unique=True)
    real_name = models.CharField('真实姓名', max_length=50, blank=True)
    role = models.CharField('角色', max_length=20, choices=ROLE_CHOICES, default='user')
    phone = models.CharField('手机号', max_length=20, blank=True)
    email = models.EmailField('邮箱', blank=True)
    is_active = models.BooleanField('是否激活', default=True)
    is_staff = models.BooleanField('是否员工', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    last_login = models.DateTimeField('最后登录', null=True, blank=True)
    
    objects = UserManager()
    
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = []
    
    class Meta:
        db_table = 'sys_user'
        verbose_name = '用户'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.username
    
    @property
    def is_super_admin(self):
        """是否是超级管理员（ID=1且角色为superadmin）"""
        return self.id == SUPERADMIN_ID and self.role == 'superadmin'
    
    @property
    def is_admin(self):
        """是否是管理员"""
        return self.role in ['superadmin', 'admin']


class OperationLog(models.Model):
    """操作日志模型"""
    
    ACTION_CHOICES = [
        ('login', '登录'),
        ('logout', '退出'),
        ('create', '创建'),
        ('update', '更新'),
        ('delete', '删除'),
        ('export', '导出'),
        ('import', '导入'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name='操作用户')
    action = models.CharField('操作类型', max_length=20, choices=ACTION_CHOICES)
    module = models.CharField('操作模块', max_length=50)
    detail = models.TextField('操作详情', blank=True)
    ip_address = models.GenericIPAddressField('IP地址', null=True, blank=True)
    user_agent = models.CharField('用户代理', max_length=500, blank=True)
    created_at = models.DateTimeField('操作时间', auto_now_add=True)
    
    class Meta:
        db_table = 'sys_operation_log'
        verbose_name = '操作日志'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user} - {self.action} - {self.module}"
