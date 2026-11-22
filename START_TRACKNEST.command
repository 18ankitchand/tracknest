#!/bin/bash
# TrackNest macOS local Django starter. No VS Code required.
set -euo pipefail
cd "$(dirname "$0")"
echo "TrackNest — Local Django website"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install Python 3.10 or newer first."
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "Creating Python virtual environment..."
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate --noinput
python manage.py check
echo "Website: http://127.0.0.1:8000/"
python manage.py runserver 127.0.0.1:8000 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT INT TERM
sleep 2
if command -v open >/dev/null 2>&1; then
  open http://127.0.0.1:8000/ || true
fi
wait "$SERVER_PID"
