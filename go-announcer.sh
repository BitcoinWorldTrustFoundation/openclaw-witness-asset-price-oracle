#!/usr/bin/env bash
# Witness BTC Price Oracle - Mainnet Launcher

ENV_FILE=".env"

if [ ! -f "$ENV_FILE" ]; then
    echo "⚠️  Configuration file not found: $ENV_FILE"
    echo "Please run ./install.sh first."
    exit 1
fi

source venv/bin/activate
export PYTHONPATH="$(dirname "$0")"

echo "🚀 Launching Witness Oracle Ecosystem (BTC + Assets)..."
python3 -m src.announcer_wrapper
