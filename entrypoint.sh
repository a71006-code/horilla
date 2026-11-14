#!/bin/bash

echo "Waiting for database to be ready..."
# Removed makemigrations from runtime to avoid permission issues and inconsistent state.
# Migrations must be committed to the repository.
python3 manage.py migrate --noinput || exit $?
mkdir -p /app/staticfiles && chmod 777 /app/staticfiles
python3 manage.py collectstatic --noinput || echo "Collectstatic failed (likely permission issue), skipping..."
gunicorn --bind 0.0.0.0:8000 horilla.wsgi:application
