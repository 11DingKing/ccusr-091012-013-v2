"""
人员管理模型
"""
from django.db import models
from PIL import Image
import os


def avatar_upload_path(instance, filename):
    """头像上传路径"""
    ext = filename.split('.')[-1]
    return f'avatars/{instance.police_no}.{ext}'


class StockOutPerson(models.Model):
    """出库人员模型"""
    police_no = models.CharField('警号', max_length=50, unique=True)
    name = models.CharField('姓名', max_length=50, unique=True)
    id_card = models.CharField('身份证号', max_length=18, blank=True)
    phone = models.CharField('手机号', max_length=20, unique=True)
    avatar = models.ImageField('蓝底照片', upload_to=avatar_upload_path, blank=True, null=True)
    binduser = models.ForeignKey(
        'authentication.User', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='stock_out_persons',
        verbose_name='关联管理员',
        limit_choices_to={'role': 'admin'}
    )
    is_active = models.BooleanField('是否在职', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'pm_stock_out_person'
        verbose_name = '出库人员'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} ({self.police_no})"
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.avatar:
            self._process_avatar()
    
    def _process_avatar(self):
        """使用Pillow处理头像图片 - 压缩和调整尺寸"""
        try:
            img = Image.open(self.avatar.path)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            max_size = (200, 200)
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            img.save(self.avatar.path, 'JPEG', quality=85, optimize=True)
        except Exception:
            pass
