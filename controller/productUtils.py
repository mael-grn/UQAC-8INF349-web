import requests
from model.product import Product

SOURCE_URL = "https://dimensweb.uqac.ca/~jgnault/shops/products/"

def sanitize(text):
    if isinstance(text, str):
        return text.replace('\x00', '')
    return text

def get_products_from_source():
    res = requests.get(SOURCE_URL)
    if res.status_code != 200:
        raise f"Erreur lors de la récupération des données : code : {res.status_code} - message : {res.text}"
    res_json = res.json()
    if res_json is None or res_json.get('products') is None:
        raise "Erreur lors de la récupération des données : données invalides"
    return res_json['products']

def upsert_product_from_json(json):
    try:
        product, created = Product.get_or_create(
            id=json['id'],
            defaults={
                "name": sanitize(json["name"]),
                "in_stock": json["in_stock"],
                "description": sanitize(json["description"]),
                "price": json["price"],
                "weight": json["weight"],
                "image": sanitize(json["image"]),
            }
        )

        if not created:
            product.name = sanitize(json['name'])
            product.in_stock = json['in_stock']
            product.description = sanitize(json['description'])
            product.price = json['price']
            product.weight = json['weight']
            product.image = sanitize(json['image'])
            product.save()
    except Exception as e:
        print(f"⚠️ Erreur avec le produit ID={json.get('id')} : {e}")

def load_products():
    products_json = get_products_from_source()
    for product_json in products_json:
        upsert_product_from_json(product_json)
