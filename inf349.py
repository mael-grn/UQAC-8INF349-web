from flask import *
import logging
from peewee import SqliteDatabase
from model.order import Order
from model.product import Product
from model.productOrder import ProductOrder
from model.requestError import RequestError
from controller.orderUtils import calculate_total_price, calculate_total_price_tax, calculate_shipping_price, \
    update_order_shipping_and_email, update_order_payment
from controller.productUtils import load_products
import re
import peewee
from model.db import db
from model.transaction import Transaction
from util.redis_client import redis_client
import json
from redis import Redis
from rq import Queue
import os
from tasks import process_payment
from cli import worker_command

# Initialisation du logger
logging.basicConfig(
    filename='app.log',  # Fichier de log
    level=logging.INFO,  # Niveau minimal des logs (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'  # Format du log
)

# Initialisation de l'application Flask
app = Flask(__name__)
logger = logging.getLogger(__name__)

# Configuration de la base de données (ex: SQLite)
DATABASE = "database.db"


# Fonction pour initialiser la base de données
def init_db():
    from model.creditCard import CreditCard
    from model.order import Order
    from model.product import Product
    from model.productOrder import ProductOrder
    from model.shippingInfo import ShippingInfo
    from model.transaction import Transaction
    db.connect()
    db.create_tables([Product, ProductOrder, ShippingInfo, CreditCard, Transaction, Order], safe=True)
    logger.info("Initialisation des produits")
    load_products()
    db.close()
    logger.info("Base de données initialisée")

# Commande Flask pour initialiser la base de données
@app.cli.command("init-db")
def init_db_command():
    """Initialise la base de données."""
    init_db()
    print("Base de données créée avec succès.")

@app.get('/')
def get_all_products():
    logger.info("Récupération de tous les produits")

    try:
        products = Product.select()
        product_list = [
            {
                "id": p.id,
                "name": p.name,
                "in_stock": bool(p.in_stock),
                "description": p.description,
                "price": p.price,
                "weight": p.weight,
                "image": p.image
            }
            for p in products
        ]
        return {"products": product_list}, 200
    except Exception as e:
        print(f"DEBUG: Erreur interne capturée dans get_all_products - {str(e)}")
        return {"error": "internal-server-error"}, 500



def contains_xss(value):
    return bool(re.search(r'<script.*?>.*?</script>', value, re.IGNORECASE))

def is_valid_email(email):
    return re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email) is not None

@app.post('/order')
def create_order():
    logger.info("Création d'une commande")
    if not request.content_type or "application/json" not in request.content_type:
        return {"errors": {"request": {"code": "invalid-content-type", "name": "Le Content-Type doit être application/json"}}}, 400

    data = request.json

    # Support du format unique (ancien)
    products_data = []
    if 'product' in data:
        products_data = [data['product']]
    elif 'products' in data and isinstance(data['products'], list):
        products_data = data['products']
    else:
        return {"errors": {"product": {"code": "missing-fields", "name": "Aucun produit fourni"}}}, 422

    if not products_data:
        return {"errors": {"product": {"code": "missing-fields", "name": "La liste de produits est vide"}}}, 422

    # Création de la commande
    order = Order.create()

    for p in products_data:
        try:
            product_id = int(p["id"])
            quantity = int(p["quantity"])
        except (KeyError, ValueError):
            return {"errors": {"product": {"code": "invalid-fields", "name": "Champs ID ou quantité manquants ou invalides"}}}, 422

        product = Product.get_or_none(Product.id == product_id)
        if not product:
            return {"errors": {"product": {"code": "not-found", "name": f"Produit ID {product_id} introuvable"}}}, 404
        if quantity <= 0 or product.in_stock < quantity:
            return {"errors": {"product": {"code": "invalid-quantity", "name": "Quantité demandée invalide ou trop élevée"}}}, 422

        ProductOrder.create(order=order, product=product, quantity=quantity)

    logger.info(f"Commande {order.id} créée avec {len(products_data)} produits")
    return {"order_link": f"/order/{order.id}"}, 201


@app.get('/order/<int:order_id>')
def get_order(order_id):
    logger.info(f"Récupération de la commande {order_id}")

    cached = redis_client.get(f"order:{order_id}")
    if not cached:
        order = Order.select(Order, Transaction).join(Transaction, peewee.JOIN.LEFT_OUTER).where(Order.id == order_id).first()

        if not order:
            return {"error": "order-not-found"}, 404

        # ✅ ICI : vérifie si le paiement est en cours
        if order.paying and not order.paid:
            return "", 202

    if cached:
        logger.info(f"Commande {order_id} chargée depuis Redis ✅")
        return {"order": json.loads(cached)}, 200

    # Récupération de la commande
    order = Order.select(Order, Transaction).join(Transaction, peewee.JOIN.LEFT_OUTER).where(Order.id == order_id).first()

    # Vérification de l'existence de la commande, sinon erreur 404
    if not order:
        logger.error("La commande demandée n'existe pas")
        return {"error": "order-not-found"}, 404

    # Récupération des produits de la commande
    product_order_res = ProductOrder.select().where(ProductOrder.order == order)
    product_order = list(product_order_res)
    print(f"product_order : {product_order}")
    # Si aucun produit n'a été attribué à la commande
    if len(product_order) == 0:
        logger.error("La commande est vide")
        return {"error": "order-empty"}, 404

    """# Si la commande a plus d'un seul produit
    if len(product_order) > 1:
        logger.error("La commande contient plusieurs produits")
        return {"error": "multiple-products"}, 422"""

    # Conversion en dictionnaire
    order_data = order.__data__

    # Ajout des propriétés manquantes
    order_data["products"] = [
        {
            "id": po.product.id,
            "quantity": po.quantity
        }
        for po in product_order
    ]
    order_data["total_price"] = calculate_total_price(order)
    order_data['total_price_tax'] = calculate_total_price_tax(order)
    order_data['shipping_price'] = calculate_shipping_price(order)
    order_data['shipping_information'] = order.shipping_information.__data__ if order.shipping_information else {}
    if order.transaction:
        transaction_data = {
            "id": order.transaction.id,
            "success": order.transaction.success,
            "amount": order.transaction.amount
        }

        if not order.transaction.success:
            transaction_data["error"] = {
                "code": getattr(order.transaction, "error_code", "card-declined"),
                "name": getattr(order.transaction, "error_message", "La carte de crédit a été déclinée.")
            }

        order_data["transaction"] = transaction_data

    logger.info(f"Commande {order_id} récupérée avec succès")
    if not order.transaction:
        order.transaction = None

    return {"order": order_data}

@app.delete('/order/<int:order_id>')
def delete_order(order_id):
    logger.info(f"Suppression de la commande {order_id}")

    # Récupération de la commande
    order = Order.get_or_none(Order.id == order_id)

    # Vérification de l'existence de la commande, sinon erreur 404
    if not order:
        logger.error("La commande demandée n'existe pas")
        return {"error": "order-not-found"}, 404

    # Suppression de la commande
    order.delete_instance()
    logger.info(f"Commande {order_id} supprimée avec succès")

    return {"message": "Commande supprimée avec succès"}, 200

@app.put('/order/<int:order_id>')
def update_order(order_id):
    logger.info(f"Mise à jour de la commande {order_id}")

    # Récupération de la commande
    order = Order.get_or_none(Order.id == order_id)

    # Vérification de l'existence de la commande, sinon erreur 404
    if not order:
        logger.error("La commande demandée n'existe pas")
        return {"error": "order-not-found"}, 404

    # Récupération des données de la requête
    data = request.json

    if not data:
        logger.error("La requête ne contient pas les champs nécessaires")
        print(f"DEBUG: Raison du 422 - {order.__data__}")
        return {
            "errors": {
                "order": {
                    "code": "missing-fields",
                    "name": "La mise à jour d'une commande nécessite des informations"
                }
            }
        }, 422

    # On redirige vers la fonction appropriée en fonction des données reçues
    if "order" in data and "email" in data["order"] and "shipping_information" in data["order"] and not "credit_card" in data:
        print(f"DEBUG: Raison du 422 - {order.__data__}")
        if not is_valid_email(request.json["order"]["email"]):
            return {
                "errors": {
                    "email": {
                        "code": "invalid-email",
                        "name": "L'email fourni est invalide"
                    }
                }
            }, 422
        logger.info(f"Mise à jour de l'adresse et de l'email de la commande {order_id}")

        # Mise à jour des données
        try:
            update_order_shipping_and_email(order, data)
            # Retourne la commande complète
            logger.info(f"Commande {order_id} mise à jour avec succès")
            return get_order(order.id)

        except RequestError as e:
            logger.error(f"Erreur lors de la mise à jour de la commande {order_id}")
            return {
                "errors": {
                    "order": {
                        "code": str(e),
                        "name": e.details
                    }
                }
            }, e.code


    elif "credit_card" in data and not "order" in data:

        if order.paid:
            return {

                "errors": {

                    "order": {

                        "code": "already-paid",

                        "name": "La commande est déjà payée"

                    }

                }

            }, 400

        if order.paying:
            return {

                "errors": {

                    "order": {

                        "code": "payment-in-progress",

                        "name": "Le paiement est déjà en cours"

                    }

                }

            }, 409
        redis_conn = Redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379"))
        task_queue = Queue(connection=redis_conn)

        order.paying = True
        order.save()

        task_queue.enqueue(process_payment, order.id, data["credit_card"])
        print(f"🌀 Tâche de paiement enfilée pour commande {order.id}")
        return "", 202
    else:
        print(f"DEBUG: Raison du 422 - {order.__data__}")
        logger.error("La requête ne contient pas les champs nécessaires")
        return {
            "errors": {
                "order": {
                    "code": "missing-fields",
                    "name": "La mise à jour d'une commande nécessite des informations d'une adresse et d'un email, ou d'une carte de crédit"
                }
            }
        }, 422

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
app.cli.add_command(worker_command)