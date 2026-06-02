#!/bin/bash

echo "Waiting for database to be ready..."
# Removed makemigrations from runtime to avoid permission issues and inconsistent state.
# Migrations must be committed to the repository.
python3 manage.py migrate --noinput
mkdir -p /app/staticfiles && chmod 777 /app/staticfiles
python3 manage.py collectstatic --noinput || echo "Collectstatic failed (likely permission issue), skipping..."
python3 manage.py createhorillauser --first_name admin --last_name admin --username admin --password admin --email admin@example.com --phone 1234567890
gunicorn --bind 0.0.0.0:8000 horilla.wsgi:application
