#!/usr/bin/env bash
set -euo pipefail

BUNDLE_PATH=""
SECRETS_PATH=""
APP_DIR="/opt/gtv-elevadores-01"
APP_USER="gtvapp"
SERVICE_NAME="gtv-elevadores-01"
RESET_DATA="false"
PERSISTENT_DATA_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bundle)
      BUNDLE_PATH="$2"
      shift 2
      ;;
    --secrets)
      SECRETS_PATH="$2"
      shift 2
      ;;
    --app-dir)
      APP_DIR="$2"
      shift 2
      ;;
    --app-user)
      APP_USER="$2"
      shift 2
      ;;
    --service-name)
      SERVICE_NAME="$2"
      shift 2
      ;;
    --reset-data)
      RESET_DATA="$2"
      shift 2
      ;;
    *)
      echo "Parametro no reconocido: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$BUNDLE_PATH" || -z "$SECRETS_PATH" ]]; then
  echo "Debes indicar --bundle y --secrets." >&2
  exit 1
fi

PERSISTENT_DATA_DIR="${APP_DIR}/data"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip ca-certificates tar build-essential

if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$APP_USER"
fi

mkdir -p "$APP_DIR"

if [[ "$RESET_DATA" == "true" ]]; then
  rm -rf "$PERSISTENT_DATA_DIR"
fi

mkdir -p "$PERSISTENT_DATA_DIR"
if [[ -d "$APP_DIR/app/data" && "$RESET_DATA" != "true" ]]; then
  cp -a "$APP_DIR/app/data/." "$PERSISTENT_DATA_DIR/" 2>/dev/null || true
fi

rm -rf "$APP_DIR/app"
mkdir -p "$APP_DIR/app"
tar -xzf "$BUNDLE_PATH" -C "$APP_DIR/app"

mkdir -p "$APP_DIR/app/.streamlit"
install -m 600 "$SECRETS_PATH" "$APP_DIR/app/.streamlit/secrets.toml"

rm -rf "$APP_DIR/app/data"
ln -s "$PERSISTENT_DATA_DIR" "$APP_DIR/app/data"

python3 -m venv "$APP_DIR/app/.venv"
"$APP_DIR/app/.venv/bin/pip" install --upgrade pip
"$APP_DIR/app/.venv/bin/pip" install -r "$APP_DIR/app/requirements.txt"

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

runuser -u "$APP_USER" -- bash -lc "cd '$APP_DIR/app' && ./.venv/bin/python scripts/init_db.py"

cat >/etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=GTV Elevadores Streamlit
After=network.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}/app
Environment=HOME=${APP_DIR}/app
Environment=PYTHONUNBUFFERED=1
ExecStart=${APP_DIR}/app/.venv/bin/streamlit run app.py --server.address 0.0.0.0 --server.port 8501
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service"
systemctl restart "${SERVICE_NAME}.service"
systemctl --no-pager --full status "${SERVICE_NAME}.service" || true
