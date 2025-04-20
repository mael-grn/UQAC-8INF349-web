from controller.orderUtils import update_order_payment
from model.order import Order

def process_payment(order_id, credit_card_data):
    print(f"🧾 Traitement du paiement pour la commande {order_id} en cours...")

    order = Order.get_by_id(order_id)
    try:
        update_order_payment(order, {"credit_card": credit_card_data})

        # Vérifie après mise à jour si c'était réussi ou non
        if order.transaction and order.transaction.success:
            print(f"✅ Paiement accepté pour la commande {order_id}")
        else:
            print(f"❌ Paiement refusé pour la commande {order_id} - {order.transaction.error_message or 'Erreur inconnue'}")

    except Exception as e:
        print(f"🔥 Erreur inattendue lors du paiement : {e}")

    finally:
        order.paying = False
        order.save()
