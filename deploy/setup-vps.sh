#!/usr/bin/env bash
set -euo pipefail

# VPS setup script for the forward paper trading service.
# Run this once on a fresh Ubuntu/Debian VPS.
#
# Usage: bash deploy/setup-vps.sh

echo "=== FX Forward Paper Trading — VPS Setup ==="

# 1. System packages
echo "[1/6] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq docker.io docker-compose-plugin curl git

# 2. Docker permissions
echo "[2/6] Configuring Docker..."
sudo usermod -aG docker "$USER"
sudo systemctl enable docker
sudo systemctl start docker

# 3. Clone / copy repo
echo "[3/6] Setting up project directory..."
INSTALL_DIR="/opt/fx-smc-bot"
if [ ! -d "$INSTALL_DIR" ]; then
    sudo mkdir -p "$INSTALL_DIR"
    sudo chown "$USER:$USER" "$INSTALL_DIR"
    echo "  Copy your repo to $INSTALL_DIR or:"
    echo "    git clone <your-repo-url> $INSTALL_DIR"
fi

# 4. Data directory
echo "[4/6] Creating data directories..."
sudo mkdir -p /data/fx/{real,live}
sudo chown -R "$USER:$USER" /data/fx

# 5. Environment file
echo "[5/6] Environment configuration..."
if [ ! -f "$INSTALL_DIR/.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env" 2>/dev/null || true
    echo "  Edit $INSTALL_DIR/.env to set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
fi

# 6. Scheduled reports
echo "[6/6] Installing cron jobs..."
if [ -f "$INSTALL_DIR/deploy/crontab" ]; then
    crontab "$INSTALL_DIR/deploy/crontab"
    echo "  Cron jobs installed"
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Copy historical data to /data/fx/real/"
echo "  2. Edit $INSTALL_DIR/.env (set Telegram credentials)"
echo "  3. cd $INSTALL_DIR && docker compose build"
echo "  4. docker compose up -d forward-paper"
echo "  5. docker compose logs -f forward-paper"
echo ""
echo "Note: you may need to log out and back in for Docker group permissions."
