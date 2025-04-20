from peewee import *

from peewee import *
from model.db import db

class ShippingInfo(Model):
    id = AutoField(primary_key=True)
    country = CharField()
    address = CharField()
    postal_code = CharField()
    city = CharField()
    province = CharField()

    class Meta:
        database = db