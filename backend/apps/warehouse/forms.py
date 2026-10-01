"""
库房管理表单 - 使用 django-crispy-forms
"""
from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Field, Div, Row, Column
from crispy_forms.bootstrap import FormActions
from .models import Unit, Category, Variety, Goods, StockIn, StockOut


class UnitForm(forms.ModelForm):
    """单位表单 - 使用 crispy-forms 美化"""
    
    class Meta:
        model = Unit
        fields = ['name', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': '请输入单位名称'}),
            'description': forms.Textarea(attrs={'placeholder': '请输入描述', 'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Field('name', css_class='form-input'),
            Field('description', css_class='form-input'),
            Field('is_active'),
            FormActions(
                Submit('submit', '保存', css_class='btn btn-primary')
            )
        )


class CategoryForm(forms.ModelForm):
    """品类表单 - 使用 crispy-forms 美化"""
    
    class Meta:
        model = Category
        fields = ['name', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': '请输入品类名称'}),
            'description': forms.Textarea(attrs={'placeholder': '请输入描述', 'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Field('name', css_class='form-input'),
            Field('description', css_class='form-input'),
            Field('is_active'),
            FormActions(
                Submit('submit', '保存', css_class='btn btn-primary')
            )
        )


class VarietyForm(forms.ModelForm):
    """品种表单 - 使用 crispy-forms 美化"""
    
    class Meta:
        model = Variety
        fields = ['name', 'category', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': '请输入品种名称'}),
            'description': forms.Textarea(attrs={'placeholder': '请输入描述', 'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Field('name', css_class='form-input'),
            Field('category', css_class='form-select'),
            Field('description', css_class='form-input'),
            Field('is_active'),
            FormActions(
                Submit('submit', '保存', css_class='btn btn-primary')
            )
        )


class GoodsForm(forms.ModelForm):
    """货物表单 - 使用 crispy-forms 美化"""
    
    class Meta:
        model = Goods
        fields = ['code', 'name', 'variety', 'unit', 'specification', 
                  'quantity', 'warning_threshold', 'location', 'remark']
        widgets = {
            'code': forms.TextInput(attrs={'placeholder': '请输入货物编码'}),
            'name': forms.TextInput(attrs={'placeholder': '请输入货物名称'}),
            'specification': forms.TextInput(attrs={'placeholder': '请输入规格型号'}),
            'quantity': forms.NumberInput(attrs={'placeholder': '请输入数量', 'min': 0}),
            'warning_threshold': forms.NumberInput(attrs={'placeholder': '请输入预警阈值', 'min': 0}),
            'location': forms.TextInput(attrs={'placeholder': '请输入存放位置'}),
            'remark': forms.Textarea(attrs={'placeholder': '请输入备注', 'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Row(
                Column(Field('code', css_class='form-input'), css_class='col-md-6'),
                Column(Field('name', css_class='form-input'), css_class='col-md-6'),
            ),
            Row(
                Column(Field('variety', css_class='form-select'), css_class='col-md-6'),
                Column(Field('unit', css_class='form-select'), css_class='col-md-6'),
            ),
            Field('specification', css_class='form-input'),
            Row(
                Column(Field('quantity', css_class='form-input'), css_class='col-md-6'),
                Column(Field('warning_threshold', css_class='form-input'), css_class='col-md-6'),
            ),
            Field('location', css_class='form-input'),
            Field('remark', css_class='form-input'),
            FormActions(
                Submit('submit', '保存', css_class='btn btn-primary')
            )
        )


class StockInForm(forms.ModelForm):
    """入库表单 - 使用 crispy-forms 美化"""
    
    class Meta:
        model = StockIn
        fields = ['goods', 'quantity', 'batch_no', 'supplier', 'remark']
        widgets = {
            'quantity': forms.NumberInput(attrs={'placeholder': '请输入入库数量', 'min': 1}),
            'batch_no': forms.TextInput(attrs={'placeholder': '请输入批次号'}),
            'supplier': forms.TextInput(attrs={'placeholder': '请输入供应商'}),
            'remark': forms.Textarea(attrs={'placeholder': '请输入备注', 'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Field('goods', css_class='form-select'),
            Row(
                Column(Field('quantity', css_class='form-input'), css_class='col-md-6'),
                Column(Field('batch_no', css_class='form-input'), css_class='col-md-6'),
            ),
            Field('supplier', css_class='form-input'),
            Field('remark', css_class='form-input'),
            FormActions(
                Submit('submit', '确认入库', css_class='btn btn-primary')
            )
        )


class StockOutForm(forms.ModelForm):
    """出库表单 - 使用 crispy-forms 美化"""
    
    class Meta:
        model = StockOut
        fields = ['goods', 'quantity', 'receiver', 'purpose', 'remark']
        widgets = {
            'quantity': forms.NumberInput(attrs={'placeholder': '请输入出库数量', 'min': 1}),
            'receiver': forms.TextInput(attrs={'placeholder': '请输入领用人'}),
            'purpose': forms.TextInput(attrs={'placeholder': '请输入用途'}),
            'remark': forms.Textarea(attrs={'placeholder': '请输入备注', 'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Field('goods', css_class='form-select'),
            Field('quantity', css_class='form-input'),
            Row(
                Column(Field('receiver', css_class='form-input'), css_class='col-md-6'),
                Column(Field('purpose', css_class='form-input'), css_class='col-md-6'),
            ),
            Field('remark', css_class='form-input'),
            FormActions(
                Submit('submit', '提交申请', css_class='btn btn-primary')
            )
        )
