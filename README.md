# Projet - Technologies Web Avancées

Application Flask de gestion de commandes e-commerce avec :
- Paiement simulé (accepté/refusé)
-  Traitement en arrière-plan avec Redis Queue (RQ)
-  Mise en cache Redis
-  Stockage PostgreSQL (Peewee ORM)
-  API RESTful complète

---

##  Démarrage rapide

### ⚙ Prérequis

- Docker Desktop installé : https://www.docker.com/products/docker-desktop
- Docker lancé ("Docker Engine is running")
- Mode Linux containers activé

---

###  Lancement de l'application

```bash
docker-compose up --build
```

Cela lance :
- Flask API → http://localhost:5000
- PostgreSQL (port 5432)
- Redis (port 6379)

---

###  Initialiser la base PostgreSQL

```bash
docker-compose exec web flask init-db
```

---

###  Lancer le worker RQ

```bash
docker-compose exec web flask worker
```

Cela lance le traitement des paiements de manière asynchrone.

---

## Tester un cycle de commande

### 1. Créer une commande

```http
POST /order
Content-Type: application/json

{
  "products": [
    { "id": 1, "quantity": 1 }
  ]
}
```

---

### 2. Ajouter email et adresse

```http
PUT /order/<id>
Content-Type: application/json

{
  "order": {
    "email": "test@uqac.ca",
    "shipping_information": {
      "country": "Canada",
      "address": "201, rue Président-Kennedy",
      "postal_code": "H2X 3Y7",
      "city": "Chicoutimi",
      "province": "QC"
    }
  }
}
```

---

### 3. Paiement accepté (test carte valide)

```http
PUT /order/<id>
Content-Type: application/json

{
  "credit_card": {
    "name": "Alice",
    "number": "4242 4242 4242 4242",
    "expiration_year": 2026,
    "expiration_month": 12,
    "cvv": "123"
  }
}
```

---

### 4. Paiement refusé (test carte déclinée)

```http
PUT /order/<id>
Content-Type: application/json

{
  "credit_card": {
    "name": "Bob",
    "number": "4000 0000 0000 0002",
    "expiration_year": 2026,
    "expiration_month": 12,
    "cvv": "123"
  }
}
```

---

### 5. Voir une commande

```http
GET /order/<id>
```

Exemple de réponse si paiement refusé :

```json
"transaction" : {
  "success": false,
  "amount": 2810,
  "error": {
    "code": "card-declined",
    "name": "La carte de crédit a été déclinée."
  }
}
```

---

## Résilience Redis

Quand une commande est payée, elle est :
- enregistrée dans PostgreSQL ✅
- mise en cache Redis ✅

Et consultable même si Postgres est éteint :

```bash
docker stop projet-web-postgres-1
curl http://localhost:5000/order/<id>
```

---

##  Arborescence

```
projet-web/
├── model/             # Modèles Peewee
├── controller/        # Logique métier
├── inf349.py          # Flask app principale
├── tasks.py           # Worker RQ
├── cli.py             # Commandes personnalisées Flask
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md          # Ce fichier
```

---

##  Problèmes fréquents

###  Erreur Docker Engine not running

```
error during connect: open //./pipe/dockerDesktopLinuxEngine: ...
```

> ➜ Ouvre Docker Desktop  
> ➜ Attends "Docker is running"  
> ➜ Puis relance : `docker-compose up --build`

---
