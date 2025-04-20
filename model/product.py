from peewee import *

from peewee import *
from model.db import db

class Product(Model):
    id = IntegerField(primary_key=True)
    name = CharField()
    in_stock = IntegerField()
    description = TextField()
    price = FloatField()
    weight = FloatField()
    image = CharField()

    class Meta:
        database = db

    def __str__(self):
        return f"{self.name} - {self.price} (stock: {self.in_stock})"