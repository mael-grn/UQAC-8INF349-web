from peewee import *

from peewee import *
from model.db import db

class CreditCard(Model):
    id = AutoField(primary_key=True)
    name = CharField()
    first_digits = CharField()
    last_digits = CharField()
    expiration_year = IntegerField()
    expiration_month = IntegerField()

    class Meta:
        database = db