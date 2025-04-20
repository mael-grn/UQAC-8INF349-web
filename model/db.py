import os
from peewee import PostgresqlDatabase

db = PostgresqlDatabase(
    os.environ.get('DB_NAME'),
    user=os.environ.get('DB_USER'),
    password=os.environ.get('DB_PASSWORD'),
    host=os.environ.get('DB_HOST'),
    port=int(os.environ.get('DB_PORT')),
)