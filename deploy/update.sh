#!/usr/bin/env bash
# Pull the latest Deflow and restart. Run on the VPS as root.
#
#   /opt/deflow/deploy/update.sh
#
# The data directory is never touched: the hash-chained ledger is what makes
# the P&L checkable, and a deploy that resets it destroys exactly that.

set -euo pipefail
APP_DIR=/opt/deflow

# Same ownership exception as the installer: scoped to this repo, not global.
GIT=(git -c "safe.directory=${APP_DIR}")

echo "==> Fetching"
"${GIT[@]}" -C "$APP_DIR" fetch --quiet origin main
"${GIT[@]}" -C "$APP_DIR" reset --hard --quiet origin/main

echo "==> Dependencies"
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

chown -R deflow:deflow "$APP_DIR"
chmod 600 "$APP_DIR/.env"

echo "==> Restarting"
systemctl restart deflow
sleep 4
systemctl is-active --quiet deflow && echo "    deflow is running" || { journalctl -u deflow -n 40 --no-pager; exit 1; }

curl -fsS localhost:8000/api/health && echo
curl -fsS localhost:8000/api/ledger/verify && echo
