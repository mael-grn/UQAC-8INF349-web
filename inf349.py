from flask import Flask, render_template, request, redirect, url_for
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
    logger.info("Récupération de tous les produits pour l'affichage")

    try:
        products = Product.select()
        product_list = [{'id': p.id, 'name': p.name, 'price': p.price, 'in_stock': p.in_stock, 'description': p.description, 'image': p.image, 'weight': p.weight} for p in products]
        return render_template('index.html', products=product_list)

    except Exception as e:
        print(f"DEBUG: Erreur interne capturée dans get_all_products - {str(e)}")
        return {"error": "internal-server-error"}, 500



def contains_xss(value):
    return bool(re.search(r'<script.*?>.*?</script>', value, re.IGNORECASE))

def is_valid_email(email):
    return re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email) is not None

@app.post('/order')
def create_order():
    logger.info("Création d'une commande via formulaire (multi-produits)")
    if request.content_type == 'application/x-www-form-urlencoded':
        products_data = []
        for key in request.form:
            if key.startswith('products['):
                match_id = re.match(r'products\[(\d+)\]\[id\]', key)
                match_quantity = re.match(r'products\[(\d+)\]\[quantity\]', key)
                if match_id:
                    index = int(match_id.group(1))
                    product_id = request.form.get(f'products[{index}][id]')
                    quantity = request.form.get(f'products[{index}][quantity]')
                    if product_id and quantity:
                        products_data.append({'id': product_id, 'quantity': quantity})

        if not products_data:
            return render_template('error.html', error="Aucun produit sélectionné."), 400

        order = Order.create()
        for p in products_data:
            try:
                product_id = int(p["id"])
                quantity = int(p["quantity"])
            except (ValueError, TypeError):
                order.delete_instance()
                return render_template('error.html', error="ID du produit ou quantité invalide."), 422

            product = Product.get_or_none(Product.id == product_id)
            if not product:
                order.delete_instance()
                return render_template('error.html', error=f"Produit ID {product_id} introuvable."), 404
            if quantity <= 0 or product.in_stock < quantity:
                order.delete_instance()
                return render_template('error.html', error=f"Quantité invalide pour le produit ID {product_id}."), 422

            ProductOrder.create(order=order, product=product, quantity=quantity)

        logger.info(f"Commande {order.id} créée avec {len(products_data)} produits via formulaire.")
        return redirect(url_for('get_order', order_id=order.id))

    elif not request.content_type or "application/json" not in request.content_type:
        return {"errors": {"request": {"code": "invalid-content-type", "name": "Le Content-Type doit être application/json"}}}, 400
    else:
        # Logique de création de commande via API JSON
        data = request.json
        products_data_json = []
        if 'products' in data and isinstance(data['products'], list):
            products_data_json = data['products']
        else:
            return {"errors": {"product": {"code": "missing-fields", "name": "Liste de produits manquante"}}}, 422

        if not products_data_json:
            return {"errors": {"product": {"code": "missing-fields", "name": "La liste de produits est vide"}}}, 422

        order = Order.create()
        for p in products_data_json:
            try:
                product_id = int(p["id"])
                quantity = int(p["quantity"])
            except (KeyError, ValueError):
                order.delete_instance()
                return {"errors": {"product": {"code": "invalid-fields", "name": "Champs ID ou quantité manquants ou invalides"}}}, 422

            product = Product.get_or_none(Product.id == product_id)
            if not product:
                order.delete_instance()
                return {"errors": {"product": {"code": "not-found", "name": f"Produit ID {product_id} introuvable"}}}, 404
            if quantity <= 0 or product.in_stock < quantity:
                order.delete_instance()
                return {"errors": {"product": {"code": "invalid-quantity", "name": "Quantité demandée invalide ou trop élevée"}}}, 422

            ProductOrder.create(order=order, product=product, quantity=quantity)

        logger.info(f"Commande {order.id} créée avec {len(products_data_json)} produits via API JSON.")
        return {"order_link": f"/order/{order.id}"}, 201

@app.get('/order/<int:order_id>')
def get_order(order_id):
    logger.info(f"Récupération de la commande {order_id} pour affichage") 

    cached = redis_client.get(f"order:{order_id}")
    order_data = None
    if cached:
        logger.info(f"Commande {order_id} chargée depuis Redis ✅")
        order_data = json.loads(cached)
    else:
        order = Order.select(Order, Transaction).join(Transaction, peewee.JOIN.LEFT_OUTER).where(Order.id == order_id).first()

        if not order:
            return render_template('error.html', error="Commande non trouvée."), 404 

        if order.paying and not order.paid:
            return "Paiement en cours...", 202 

        order_data = order.__data__
        order_data["products"] = [
            {"id": po.product.id, "quantity": po.quantity}
            for po in ProductOrder.select().where(ProductOrder.order == order)
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
        else:
            order_data["transaction"] = None

    return render_template('order.html', order=order_data) 

@app.delete('/order/<int:order_id>')
def delete_order(order_id):
    logger.info(f"Tentative de suppression de la commande {order_id} via interface")
    try:
        order = Order.get_or_none(Order.id == order_id)
        if not order:
            return {"error": f"Commande ID {order_id} non trouvée."}, 404

        ProductOrder.delete().where(ProductOrder.order == order).execute()

        order.delete_instance()

        logger.info(f"Commande {order_id} supprimée avec succès.")
        return '', 204

    except peewee.IntegrityError as e:
        logger.error(f"Erreur d'intégrité lors de la suppression de la commande {order_id}: {e}")
        return {"error": "Impossible de supprimer la commande car des éléments y sont encore associés."}, 409
    except Exception as e:
        logger.error(f"Erreur lors de la suppression de la commande {order_id}: {e}")
        return {"error": "Erreur interne lors de la suppression de la commande."}, 500

@app.put('/order/<int:order_id>')
def update_order(order_id):
    logger.info(f"Tentative de mise à jour de la commande {order_id} via interface")
    order = Order.get_or_none(Order.id == order_id)
    if not order:
        return {"error": f"Commande ID {order_id} non trouvée."}, 404

    try:
        data = request.form if request.content_type == 'application/x-www-form-urlencoded' else request.json
        if not data:
            return {"error": "Aucune donnée de mise à jour fournie."}, 400

        shipping_address = data.get('shipping_address')
        shipping_city = data.get('shipping_city')
        shipping_postal_code = data.get('shipping_postal_code')
        shipping_country = data.get('shipping_country')
        email = data.get('email')

        if shipping_address and shipping_city and shipping_postal_code and shipping_country:
            if contains_xss(shipping_address) or contains_xss(shipping_city) or contains_xss(shipping_country):
                return {"error": "Informations de livraison invalides (XSS détecté)."}, 400
            shipping_info, created = ShippingInfo.get_or_create(
                address=shipping_address,
                city=shipping_city,
                postal_code=shipping_postal_code,
                country=shipping_country
            )
            order.shipping_information = shipping_info

        if email:
            if contains_xss(email) or not is_valid_email(email):
                return {"error": "Adresse e-mail invalide."}, 400
            order.email = email

        if shipping_address or email:
            order.save()
            logger.info(f"Commande {order_id} mise à jour avec les informations de livraison/e-mail.")
            return {"message": f"Commande {order_id} mise à jour avec succès."}, 200
        else:
            return {"message": "Aucune information de mise à jour valide fournie."}, 200

    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour de la commande {order_id}: {e}")
        return {"error": "Erreur interne lors de la mise à jour de la commande."}, 500


    
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
app.cli.add_command(worker_command)