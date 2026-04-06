#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_FILE="$HOME/.config/systemd/user/proxy.service"

PYTHON="$PROJECT_DIR/.venv/bin/python"
if [ ! -f "$PYTHON" ]; then
    echo "Error: .venv not found at $PROJECT_DIR/.venv"
    echo "Run: python -m venv .venv && source .venv/bin/activate && pip install -e ."
    exit 1
fi

mkdir -p "$HOME/.config/systemd/user"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Proxy — voice layer for your coding agent
After=network.target sound.target

[Service]
Type=simple
WorkingDirectory=$PROJECT_DIR
ExecStart=$PYTHON -m proxy.main
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable proxy.service
systemctl --user start proxy.service

echo "Proxy installed as a systemd user service."
echo "  Status:  systemctl --user status proxy"
echo "  Logs:    journalctl --user -u proxy -f"
echo "  Stop:    systemctl --user stop proxy"
echo "  Disable: systemctl --user disable proxy"
