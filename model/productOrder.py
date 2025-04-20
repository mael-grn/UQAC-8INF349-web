from peewee import *
from model.order import Order
from model.product import Product

from peewee import *
from model.db import db
class ProductOrder(Model):
    id = AutoField(primary_key=True)
    order = ForeignKeyField(Order, backref='product_orders')
    product = ForeignKeyField(Product, backref='product_orders')
    quantity = IntegerField(default=1)

    class Meta:
        database = db