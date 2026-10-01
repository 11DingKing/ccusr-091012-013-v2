"""
库房管理导入导出资源
使用django-import-export
"""
from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from .models import Unit, Category, Variety, Goods, StockIn, StockOut


class UnitResource(resources.ModelResource):
    """单位导入导出资源"""
    
    class Meta:
        model = Unit
        fields = ('id', 'name', 'symbol', 'description', 'is_active', 'created_at')
        export_order = ('id', 'name', 'symbol', 'description', 'is_active', 'created_at')


class CategoryResource(resources.ModelResource):
    """品类导入导出资源"""
    
    class Meta:
        model = Category
        fields = ('id', 'name', 'code', 'description', 'is_active', 'created_at')
        export_order = ('id', 'name', 'code', 'description', 'is_active', 'created_at')


class VarietyResource(resources.ModelResource):
    """品种导入导出资源"""
    category = fields.Field(
        column_name='category',
        attribute='category',
        widget=ForeignKeyWidget(Category, 'name')
    )
    
    class Meta:
        model = Variety
        fields = ('id', 'category', 'name', 'code', 'description', 'is_active', 'created_at')
        export_order = ('id', 'category', 'name', 'code', 'description', 'is_active', 'created_at')


class GoodsResource(resources.ModelResource):
    """货物导入导出资源"""
    variety = fields.Field(
        column_name='variety',
        attribute='variety',
        widget=ForeignKeyWidget(Variety, 'name')
    )
    unit = fields.Field(
        column_name='unit',
        attribute='unit',
        widget=ForeignKeyWidget(Unit, 'name')
    )
    
    class Meta:
        model = Goods
        fields = ('id', 'code', 'name', 'variety', 'unit', 'specification', 
                  'quantity', 'warning_threshold', 'location', 'is_active', 'created_at')
        export_order = ('id', 'code', 'name', 'variety', 'unit', 'specification',
                        'quantity', 'warning_threshold', 'location', 'is_active', 'created_at')


class StockInResource(resources.ModelResource):
    """入库记录导入导出资源"""
    goods_code = fields.Field(attribute='goods__code', column_name='goods_code')
    goods_name = fields.Field(attribute='goods__name', column_name='goods_name')
    operator_name = fields.Field(attribute='operator__username', column_name='operator')
    
    class Meta:
        model = StockIn
        fields = ('id', 'goods_code', 'goods_name', 'quantity', 'batch_no', 
                  'supplier', 'operator_name', 'stock_in_time', 'remark')
        export_order = ('id', 'goods_code', 'goods_name', 'quantity', 'batch_no',
                        'supplier', 'operator_name', 'stock_in_time', 'remark')


class StockOutResource(resources.ModelResource):
    """出库记录导入导出资源"""
    goods_code = fields.Field(attribute='goods__code', column_name='goods_code')
    goods_name = fields.Field(attribute='goods__name', column_name='goods_name')
    operator_name = fields.Field(attribute='operator__username', column_name='operator')
    
    class Meta:
        model = StockOut
        fields = ('id', 'goods_code', 'goods_name', 'quantity', 'receiver',
                  'receiver_dept', 'status', 'operator_name', 'stock_out_time', 'remark')
        export_order = ('id', 'goods_code', 'goods_name', 'quantity', 'receiver',
                        'receiver_dept', 'status', 'operator_name', 'stock_out_time', 'remark')
