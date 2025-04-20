# Dockerfile
FROM python:3.10-slim

# Variables d'environnement
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Dépendances système
RUN apt-get update && apt-get install -y build-essential libpq-dev

# Crée et utilise un dossier pour l'app
WORKDIR /app
COPY . /app
ENV FLASK_APP=app.inf349

# Installation des dépendances Python
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Lancement de l'app Flask
CMD ["flask", "run", "--host=0.0.0.0"]
