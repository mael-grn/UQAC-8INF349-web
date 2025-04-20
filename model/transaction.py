from peewee import *

from peewee import *
from model.db import db

class Transaction(Model):
    id = CharField(primary_key=True)
    success = BooleanField()
    amount = IntegerField()
    error_code = CharField(null=True)
    error_message = CharField(null=True)



    class Meta:
        database = db