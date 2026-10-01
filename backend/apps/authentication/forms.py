"""
认证模块表单 - 使用 django-crispy-forms
"""
from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Field, Div, HTML
from crispy_forms.bootstrap import FormActions
from .models import User


class LoginForm(forms.Form):
    """登录表单 - 使用 crispy-forms 美化"""
    username = forms.CharField(
        label='用户名',
        max_length=150,
        widget=forms.TextInput(attrs={
            'placeholder': '请输入用户名',
            'autocomplete': 'username',
        })
    )
    password = forms.CharField(
        label='密码',
        widget=forms.PasswordInput(attrs={
            'placeholder': '请输入密码',
            'autocomplete': 'current-password',
        })
    )
    captcha = forms.CharField(
        label='验证码',
        max_length=10,
        widget=forms.TextInput(attrs={
            'placeholder': '请输入计算结果',
            'autocomplete': 'off',
        })
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.form_class = 'login-form'
        self.helper.form_id = 'loginForm'
        self.helper.layout = Layout(
            Field('username', css_class='form-input'),
            Field('password', css_class='form-input'),
            Div(
                Field('captcha', css_class='form-input'),
                HTML('<div class="captcha-box" id="captchaBox"><span id="captchaText"></span></div>'),
                css_class='captcha-group'
            ),
            FormActions(
                Submit('submit', '登 录', css_class='btn btn-primary btn-block login-btn')
            )
        )


class UserProfileForm(forms.ModelForm):
    """用户资料表单 - 使用 crispy-forms 美化"""
    
    class Meta:
        model = User
        fields = ['real_name', 'phone', 'email', 'avatar']
        widgets = {
            'real_name': forms.TextInput(attrs={'placeholder': '请输入真实姓名'}),
            'phone': forms.TextInput(attrs={'placeholder': '请输入手机号'}),
            'email': forms.EmailInput(attrs={'placeholder': '请输入邮箱'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.form_class = 'user-profile-form'
        self.helper.layout = Layout(
            Field('real_name', css_class='form-input'),
            Field('phone', css_class='form-input'),
            Field('email', css_class='form-input'),
            Field('avatar', css_class='form-input'),
            FormActions(
                Submit('submit', '保存', css_class='btn btn-primary')
            )
        )


class ChangePasswordForm(forms.Form):
    """修改密码表单 - 使用 crispy-forms 美化"""
    old_password = forms.CharField(
        label='当前密码',
        widget=forms.PasswordInput(attrs={'placeholder': '请输入当前密码'})
    )
    new_password = forms.CharField(
        label='新密码',
        min_length=6,
        widget=forms.PasswordInput(attrs={'placeholder': '请输入新密码（至少6位）'})
    )
    confirm_password = forms.CharField(
        label='确认密码',
        widget=forms.PasswordInput(attrs={'placeholder': '请再次输入新密码'})
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Field('old_password', css_class='form-input'),
            Field('new_password', css_class='form-input'),
            Field('confirm_password', css_class='form-input'),
            FormActions(
                Submit('submit', '修改密码', css_class='btn btn-primary')
            )
        )
    
    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')
        
        if new_password and confirm_password and new_password != confirm_password:
            raise forms.ValidationError('两次输入的密码不一致')
        
        return cleaned_data
