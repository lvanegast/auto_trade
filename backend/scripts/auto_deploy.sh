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

        # Sincronización forzada de .env en la Jetson Nano
        if [ -f .env ]; then
            sed -i 's/^MAX_CONCURRENT_POSITIONS=.*/MAX_CONCURRENT_POSITIONS=4/' .env
            sed -i 's/^ALLOWED_REAL_WORKERS=.*/ALLOWED_REAL_WORKERS=/' .env
            grep -q '^MAX_CONCURRENT_POSITIONS=' .env || echo "MAX_CONCURRENT_POSITIONS=4" >> .env
            grep -q '^ALLOWED_REAL_WORKERS=' .env || echo "ALLOWED_REAL_WORKERS=" >> .env
            echo "[$(date)] 🔒 .env de la Jetson actualizado: MAX_CONCURRENT_POSITIONS=4, ALLOWED_REAL_WORKERS=vacío"
        fi

        docker restart trading_bot_backend
        echo "[$(date)] ✅ Bot reiniciado con el código nuevo con éxito."
    fi

    sleep 30
done
