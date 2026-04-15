#!/bin/bash
# LLM Visibility Dashboard — one-shot installer for Ubuntu 22.04 on
# Oracle Cloud Always Free (Ampere A1). Run as the `ubuntu` user AFTER:
#   1. cloning the repo to /home/ubuntu/Uplers-llm-visibility
#   2. creating /home/ubuntu/Uplers-llm-visibility/.env with your API keys

set -euo pipefail

APP_DIR="/home/ubuntu/Uplers-llm-visibility"
DASH_DIR="$APP_DIR/dashboard"
ENV_FILE="$APP_DIR/.env"

if [ ! -d "$DASH_DIR" ]; then
  echo "ERROR: $DASH_DIR not found. Clone the repo to $APP_DIR first."
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found."
  echo "Run: cp $DASH_DIR/deploy/.env.example $ENV_FILE && nano $ENV_FILE"
  exit 1
fi

echo "==> Installing system packages"
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip git nginx apache2-utils curl

echo "==> Opening port 80 in host firewall (Oracle Ubuntu images use iptables)"
# iptables rule for Oracle's default Ubuntu image
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT || true
sudo netfilter-persistent save || sudo sh -c "iptables-save > /etc/iptables/rules.v4" || true

echo "==> Setting up Python venv"
cd "$DASH_DIR"
python3 -m venv venv
./venv/bin/pip install --upgrade pip --quiet
./venv/bin/pip install -r requirements.txt --quiet

echo "==> Installing systemd service"
sudo cp "$DASH_DIR/deploy/visibility-dashboard.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable visibility-dashboard
sudo systemctl restart visibility-dashboard

echo "==> Configuring nginx"
if [ ! -f /etc/nginx/.htpasswd ]; then
  echo
  echo "Create a basic-auth login for the team:"
  read -r -p "  Username: " BA_USER
  sudo htpasswd -c /etc/nginx/.htpasswd "$BA_USER"
fi

sudo cp "$DASH_DIR/deploy/nginx.conf" /etc/nginx/sites-available/visibility-dashboard
sudo ln -sf /etc/nginx/sites-available/visibility-dashboard /etc/nginx/sites-enabled/visibility-dashboard
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

PUBLIC_IP="$(curl -s ifconfig.me || echo UNKNOWN)"
echo
echo "==================================================="
echo "  ✅ Dashboard is live"
echo "  URL:  http://$PUBLIC_IP"
echo "  Auth: the username/password you just entered"
echo "==================================================="
echo
echo "Commands you may need later:"
echo "  Restart app:   sudo systemctl restart visibility-dashboard"
echo "  View logs:     tail -f /var/log/visibility-dashboard.log"
echo "  Update code:   cd $APP_DIR && git pull && sudo systemctl restart visibility-dashboard"
echo "  Add user:      sudo htpasswd /etc/nginx/.htpasswd <name>"
