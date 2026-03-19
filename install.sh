#!/usr/bin/env bash
# Witness Oracle Ecosystem - Setup Script

echo "========================================================="
echo "   Witness Oracle Ecosystem (Mainnet v1.0) Setup"
echo "========================================================="

# 1. Environment Configuration
ENV_FILE=".env"
if [ -f "$ENV_FILE" ]; then
    echo "✅ Configuration file already exists."
else
    echo "📦 Creating .env from template..."
    cp .env.example "$ENV_FILE" 2>/dev/null || echo "⚠️  .env.example not found. Create $ENV_FILE manually."
fi

# 2. Virtual Environment Setup
if [ ! -d "venv" ]; then
    echo "🔨 Creating virtual environment..."
    python3 -m venv venv
fi

echo "🚀 Installing dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -e .

echo ""
echo "Next steps:"
echo "1. Edit .env with your Telegram Bot Token and RPC providers"
echo "2. Run: ./go-announcer.sh"
echo ""
echo "The Witness Oracle is now ready to mine truth for sats."
echo "========================================================="
