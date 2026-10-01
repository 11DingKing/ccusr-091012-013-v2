"""
人员管理序列化器
"""
from rest_framework import serializers
from .models import StockOutPerson
from apps.authentication.models import User


class StockOutPersonSerializer(serializers.ModelSerializer):
    """出库人员序列化器"""
    binduser_name = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    
    class Meta:
        model = StockOutPerson
        fields = [
            'id', 'police_no', 'name', 'id_card', 'phone', 
            'avatar', 'avatar_url', 'binduser', 'binduser_name',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_binduser_name(self, obj):
        """获取关联管理员用户名"""
        if obj.binduser:
            return obj.binduser.username
        return None
    
    def get_avatar_url(self, obj):
        """获取头像URL"""
        if obj.avatar:
            return obj.avatar.url
        return None


class StockOutPersonCreateSerializer(serializers.Serializer):
    """出库人员创建序列化器"""
    police_no = serializers.CharField(max_length=50, required=True, error_messages={
        'required': '请输入警号',
        'blank': '警号不能为空',
    })
    name = serializers.CharField(max_length=50, required=True, error_messages={
        'required': '请输入姓名',
        'blank': '姓名不能为空',
    })
    id_card = serializers.CharField(max_length=18, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=20, required=True, error_messages={
        'required': '请输入手机号',
        'blank': '手机号不能为空',
    })
    binduser = serializers.IntegerField(required=False, allow_null=True)
    
    def validate_police_no(self, value):
        instance = self.context.get('instance')
        if instance:
            if StockOutPerson.objects.filter(police_no=value).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('警号已存在')
        else:
            if StockOutPerson.objects.filter(police_no=value).exists():
                raise serializers.ValidationError('警号已存在')
        return value
    
    def validate_name(self, value):
        instance = self.context.get('instance')
        if instance:
            if StockOutPerson.objects.filter(name=value).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('姓名已存在')
        else:
            if StockOutPerson.objects.filter(name=value).exists():
                raise serializers.ValidationError('姓名已存在')
        return value
    
    def validate_phone(self, value):
        instance = self.context.get('instance')
        if instance:
            if StockOutPerson.objects.filter(phone=value).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('手机号已存在')
        else:
            if StockOutPerson.objects.filter(phone=value).exists():
                raise serializers.ValidationError('手机号已存在')
        return value
    
    def validate_binduser(self, value):
        if value:
            try:
                user = User.objects.get(pk=value)
                if user.role not in ['admin']:
                    raise serializers.ValidationError('只能绑定管理员用户')
            except User.DoesNotExist:
                raise serializers.ValidationError('用户不存在')
        return value


class AdminUserSerializer(serializers.ModelSerializer):
    """管理员用户序列化器（用于下拉选择）"""
    class Meta:
        model = User
        fields = ['id', 'username']
