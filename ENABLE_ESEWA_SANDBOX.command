#!/bin/bash
# eSewa sandbox configuration for TrackNest on macOS (no VS Code needed).
set -euo pipefail
CONFIG_DIR="$HOME/.tracknest"
CONFIG_FILE="$CONFIG_DIR/esewa.json"
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
echo "TrackNest — eSewa SANDBOX setup"
echo "This enables TEST merchant checkout only; no live money is transferred."
echo "Open https://developer.esewa.com.np/pages/Epay and find the UAT test secret."
echo
read -r -p "Sandbox product code [EPAYTEST]: " PRODUCT
PRODUCT="${PRODUCT:-EPAYTEST}"
if [[ ! "$PRODUCT" =~ ^[a-zA-Z0-9-]+$ ]]; then
  echo "Invalid product code."; exit 1
fi
read -r -s -p "eSewa UAT secret key: " SECRET
echo
if [ -z "$SECRET" ]; then
  echo "Secret key cannot be empty."; exit 1
fi
export TRACKNEST_TEST_PRODUCT="$PRODUCT" TRACKNEST_TEST_SECRET="$SECRET" TRACKNEST_TEST_CONFIG="$CONFIG_FILE"
python3 - <<'PY'
import json, os, stat
from pathlib import Path
p=Path(os.environ["TRACKNEST_TEST_CONFIG"])
p.write_text(json.dumps({
    "enabled": True,
    "product_code": os.environ["TRACKNEST_TEST_PRODUCT"],
    "secret_key": os.environ["TRACKNEST_TEST_SECRET"],
}, indent=2)+"\n", encoding="utf-8")
p.chmod(stat.S_IRUSR | stat.S_IWUSR)
print("Private eSewa sandbox settings saved on your Mac.")
print("Restart the TrackNest launcher. Then open Expenses to test eSewa sandbox.")
print("Never use real wallet credentials in this configuration.")
PY
unset TRACKNEST_TEST_SECRET SECRET
