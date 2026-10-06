#!/usr/bin/env bash
# Reconcile the existing Replit Python environment without creating another one.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

requirements="$(mktemp)"
trap 'rm -f "$requirements"' EXIT
uv export --frozen --no-dev --no-emit-project --format requirements-txt > "$requirements"
uv pip install --python "$(command -v python)" --requirement "$requirements"

cd EduBac
python manage.py check
python manage.py migrate --noinput
