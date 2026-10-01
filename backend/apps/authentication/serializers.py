"""
认证序列化器
"""
from rest_framework import serializers
from .models import User, OperationLog


class LoginSerializer(serializers.Serializer):
    """登录序列化器"""
    username = serializers.CharField(max_length=50, required=True, error_messages={
        'required': '请输入用户名',
        'blank': '用户名不能为空',
    })
    password = serializers.CharField(max_length=128, required=True, error_messages={
        'required': '请输入密码',
        'blank': '密码不能为空',
    })


class UserSerializer(serializers.ModelSerializer):
    """用户序列化器"""
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    is_super_admin = serializers.BooleanField(read_only=True)
    is_admin = serializers.BooleanField(read_only=True)
    stock_out_person_count = serializers.SerializerMethodField()
    stock_out_persons = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = [
            'id', 'username', 'real_name', 'role', 'role_display',
            'phone', 'email', 'is_active', 'is_staff', 'is_super_admin', 'is_admin',
            'created_at', 'updated_at', 'last_login',
            'stock_out_person_count', 'stock_out_persons'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'last_login']
    
    def get_stock_out_person_count(self, obj):
        """获取关联的出库人员数量"""
        return obj.stock_out_persons.count()
    
    def get_stock_out_persons(self, obj):
        """获取关联的出库人员信息"""
        persons = obj.stock_out_persons.all()
        return [{
            'id': p.id,
            'name': p.name,
            'police_no': p.police_no,
            'phone': p.phone
        } for p in persons]


class UserCreateSerializer(serializers.Serializer):
    """用户创建序列化器"""
    username = serializers.CharField(max_length=50, required=True, error_messages={
        'required': '请输入用户名',
        'blank': '用户名不能为空',
    })
    password = serializers.CharField(max_length=128, required=True, error_messages={
        'required': '请输入密码',
        'blank': '密码不能为空',
    })
    confirm_password = serializers.CharField(max_length=128, required=True, error_messages={
        'required': '请确认密码',
        'blank': '确认密码不能为空',
    })
    role = serializers.ChoiceField(choices=User.ROLE_CHOICES, default='user')
    
    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError('两次输入的密码不一致')
        return data


class OperationLogSerializer(serializers.ModelSerializer):
    """操作日志序列化器"""
    user_name = serializers.CharField(source='user.username', read_only=True)
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    
    class Meta:
        model = OperationLog
        fields = [
            'id', 'user', 'user_name', 'action', 'action_display',
            'module', 'detail', 'ip_address', 'user_agent', 'created_at'
        ]
