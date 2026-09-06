#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/auto_deploy.sh"

chmod +x "$SCRIPT_PATH"

echo "Instalando servicio systemd para $USER..."

sudo tee /etc/systemd/system/bot-autodeploy.service > /dev/null << EOF
[Unit]
Description=Auto Deploy Bot Service
After=network.target docker.service

[Service]
Type=simple
User=$USER
ExecStart=$SCRIPT_PATH
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable bot-autodeploy.service
sudo systemctl restart bot-autodeploy.service

echo "✅ Servicio bot-autodeploy instalado y activo."
sudo systemctl status bot-autodeploy.service --no-pager
