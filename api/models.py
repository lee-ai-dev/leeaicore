from django.db import models

from leeaicore.sysutils.models import TimeStampedModel

class Dish(TimeStampedModel):
    restaurant = models.ForeignKey('Restaurant', on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    description = models.CharField(max_length=500)
    currency = models.CharField(max_length=5, default='GHC')
    price = models.PositiveIntegerField(default=0)
    type = models.CharField(max_length=50)
    tag = models.CharField(max_length=20)
    availability = models.CharField(max_length=50, default='Always Available')

    def __str__(self):
        return f"{self.name}"
