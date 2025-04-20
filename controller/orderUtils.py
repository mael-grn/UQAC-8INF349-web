import uuid

from model.creditCard import CreditCard
from model.productOrder import ProductOrder
from model.requestError import RequestError
from model.transaction import Transaction
from controller.creditCardUtils import check_credit_card_entity_complete, \
    send_card_data_distant_payment
from controller.shippingInfoUtils import create_shipping_info_entity_or_none
import json
from util.redis_client import redis_client
from model.transaction import Transaction
from model.creditCard import CreditCard
from model.requestError import RequestError

TAXE_RATE = {
    "QC": 0.15,
    "NS": 0.14,
    "ON": 0.13,
    "BC": 0.12,
    "AB": 0.05,
}


def calculate_total_price(order):
    product_orders = ProductOrder.select().where(ProductOrder.order == order)

    # Si aucun produit trouvé, retourner 0
    if not product_orders.exists():
        return 0

    # Calcul du prix total
    total_price = sum(po.product.price * po.quantity for po in product_orders)

    return total_price

def calculate_total_price_tax(order):
    # Calcul du prix total avec taxes selon la province. Si la province n'est pas dans la liste, on retourne le prix total sans taxes
    if order :
        if order.shipping_information:
            if order.shipping_information :
                if order.shipping_information.province in TAXE_RATE:
                    return calculate_total_price(order) * (1 + TAXE_RATE[order.shipping_information.province])
    return calculate_total_price(order)


def calculate_shipping_price(order):
    # Calcul du poids total
    total_weight = sum(po.product.weight * po.quantity for po in ProductOrder.select().where(ProductOrder.order == order))

    # Calcul du prix de la livraison
    if total_weight <= 500:
        return 5
    elif total_weight <= 2000:
        return 10
    else:
        return 25

def check_ready_for_payment(order):

    # Si elle est déjà payée, erreur 400
    if order.paid:
        raise RequestError("already-paid", 400, "Il n'est pas possible de payer une commande déjà payée")

    # Vérification de la présence des champs nécessaires pour l'adresse, sinon erreur 422
    if not order.shipping_information:
        raise RequestError("missing-fields", 422, "Il n'est pas possible de payer une commande sans adresse de livraison")

    # Vérification de la présence de l'email, sinon erreur 422
    if not order.email:
        raise RequestError("missing-fields", 422, "Il n'est pas possible de payer une commande sans email")


def update_order_shipping_and_email(order, data):
    shipping_info = create_shipping_info_entity_or_none(data["order"].get("shipping_information", {}))
    if not shipping_info:
        raise RequestError("missing-fields", 422, "La mise à jour d'une commande nécessite une adresse de livraison")

    # Mise à jour de la commande
    order.email = data["order"]["email"]
    order.shipping_information = shipping_info

    # Sauvegarde de la commande
    order.save()


def update_order_payment(order, data):
    # Verification des champs necessaires
    check_ready_for_payment(order)
    check_credit_card_entity_complete(data.get("credit_card", {}))

    try:
        res = send_card_data_distant_payment(
            data["credit_card"],
            calculate_total_price_tax(order) + calculate_shipping_price(order)
        )

        credit_card = CreditCard.create(
            name=res["credit_card"]["name"],
            first_digits=res["credit_card"]["first_digits"],
            last_digits=res["credit_card"]["last_digits"],
            expiration_year=res["credit_card"]["expiration_year"],
            expiration_month=res["credit_card"]["expiration_month"],
            cvv=res["credit_card"].get("cvv", "000")
        )

        transaction = Transaction.create(
            id=res["transaction"]["id"],
            success=True,
            amount=res["transaction"]["amount_charged"]
        )

        order.credit_card = credit_card
        order.transaction = transaction
        order.paid = True
        order.save()

    except RequestError as e:
        # 💥 En cas d'erreur de paiement retournée par le service externe
        transaction = Transaction.create(
            id=str(uuid.uuid4()),
            success=False,
            amount=calculate_total_price_tax(order) + calculate_shipping_price(order),
            error_code=e.code,
            error_message=e.details
        )

        order.transaction = transaction
        order.paid = False
        order.save()

    # 🔁 Caching de la commande dans Redis
    cached_order = serialize_order(order)
    redis_client.set(f"order:{order.id}", json.dumps(cached_order))


def serialize_order(order):
    from model.productOrder import ProductOrder
    from controller.orderUtils import calculate_total_price, calculate_shipping_price

    product_orders = ProductOrder.select().where(ProductOrder.order == order)
    return {
        "id": order.id,
        "email": order.email,
        "paid": order.paid,
        "total_price": calculate_total_price(order),
        "shipping_price": calculate_shipping_price(order),
        "credit_card": order.credit_card.__data__ if order.credit_card else {},
        "shipping_information": order.shipping_information.__data__ if order.shipping_information else {},
        "transaction": order.transaction.__data__ if order.transaction else {},
        "products": [
            {"id": po.product.id, "quantity": po.quantity}
            for po in product_orders
        ]
    }

# 🔽 à la fin de update_order_payment()
