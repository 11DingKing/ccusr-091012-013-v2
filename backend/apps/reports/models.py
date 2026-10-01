"""
报表模型
"""
from django.db import models


class DailyReport(models.Model):
    """每日报表模型"""
    report_date = models.DateField('报表日期', unique=True)
    in_count = models.IntegerField('入库次数', default=0)
    in_total = models.DecimalField('入库总量', max_digits=12, decimal_places=2, default=0)
    out_count = models.IntegerField('出库次数', default=0)
    out_total = models.DecimalField('出库总量', max_digits=12, decimal_places=2, default=0)
    warning_count = models.IntegerField('预警数量', default=0)
    summary = models.TextField('报表摘要', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    
    class Meta:
        db_table = 'rp_daily_report'
        verbose_name = '每日报表'
        verbose_name_plural = verbose_name
        ordering = ['-report_date']
    
    def __str__(self):
        return f"报表 - {self.report_date}"
