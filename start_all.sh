#!/bin/bash
# YubiLab - Start All Services
# Usage: ./start_all.sh

set -e

YUBILAB_DIR="$(cd "$(dirname "$0")" && pwd)"
NGROK_AUTH_TOKEN="${NGROK_AUTH_TOKEN:-3BLYdMy1KhWPvdFym14RZZxmk4w_7FbEi7WjXzZHL9diBFyYc}"

# Flutter & Android SDK
export PATH="$HOME/flutter/bin:$HOME/android-sdk/cmdline-tools/latest/bin:$HOME/android-sdk/platform-tools:$PATH"
export ANDROID_HOME="$HOME/android-sdk"

echo "=== Starting YubiLab Services ==="

# 1. Start Flask Backend
echo "[1/4] Starting Flask Backend (port 5000)..."
cd "$YUBILAB_DIR/flask_backend"
export YUBIAI_API_KEY="${YUBIAI_API_KEY:-}"
nohup python app.py > "$YUBILAB_DIR/logs/flask.log" 2>&1 &
echo "  PID: $!"

# 2. Start Node Engine
echo "[2/4] Starting Node Engine (port 3001)..."
cd "$YUBILAB_DIR/node_engine"
nohup node server.js > "$YUBILAB_DIR/logs/node.log" 2>&1 &
echo "  PID: $!"

# 3. Start Proxy
echo "[3/4] Starting Proxy (port 8888)..."
cd "$YUBILAB_DIR"
nohup node proxy.js > "$YUBILAB_DIR/logs/proxy.log" 2>&1 &
echo "  PID: $!"

# 4. Start ngrok
echo "[4/4] Starting ngrok tunnel (port 8888)..."
ngrok config add-authtoken "$NGROK_AUTH_TOKEN" 2>/dev/null || true
nohup ngrok http 8888 --log=stdout > "$YUBILAB_DIR/logs/ngrok.log" 2>&1 &
echo "  PID: $!"

sleep 3

# Show ngrok URL
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])" 2>/dev/null || echo "ngrok not ready yet")
echo ""
echo "=== YubiLab is running! ==="
echo "  Local:  http://localhost:8888"
echo "  Public: $NGROK_URL"
echo ""
echo "Logs: $YUBILAB_DIR/logs/"
