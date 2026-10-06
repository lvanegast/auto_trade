#!/bin/bash
REPO_DIR="/home/lvant/Documents/auto_trade"
BRANCH="feat/executable-arbitrage-engine"

cd "$REPO_DIR" || exit 1

echo "[$(date)] Auto-deploy service iniciado para $BRANCH"

while true; do
    git fetch origin "$BRANCH" --quiet 2>/dev/null
    LOCAL_HASH=$(git rev-parse HEAD)
    REMOTE_HASH=$(git rev-parse origin/"$BRANCH" 2>/dev/null)

    if [ -n "$REMOTE_HASH" ] && [ "$LOCAL_HASH" != "$REMOTE_HASH" ]; then
        echo "[$(date)] 🚀 Nuevo push detectado ($REMOTE_HASH). Actualizando..."
        git pull origin "$BRANCH"
        docker restart trading_bot_backend
        echo "[$(date)] ✅ Bot reiniciado con el código nuevo con éxito."
    fi

    sleep 30
done
