from django.db import models


class TimeDimension(models.Model):
    """Pre-populated calendar dimension"""
    date_id = models.IntegerField(primary_key=True)
    full_date = models.DateField(unique=True)
    year = models.IntegerField()
    quarter = models.IntegerField()
    month = models.IntegerField()
    month_name = models.CharField(max_length=20)
    week = models.IntegerField()
    day_of_month = models.IntegerField()
    day_of_week = models.IntegerField()
    day_name = models.CharField(max_length=20)
    is_weekend = models.BooleanField()
    is_holiday = models.BooleanField(default=False)
    fiscal_year = models.IntegerField(null=True, blank=True)
    fiscal_quarter = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'dim_time'

    def __str__(self):
        return str(self.full_date)
