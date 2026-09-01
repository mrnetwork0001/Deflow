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

# Refresh the unit if it changed upstream, preserving the installed port.
# Without this a fix to the service file ships in the repo and never reaches
# systemd, so the deployment silently keeps running the old definition.
echo "==> Service unit"
PORT_NOW=$(grep -E '^DEFLOW_PORT=' "$APP_DIR/.env" | tail -1 | cut -d= -f2 | tr -d ' "')
PORT_NOW="${PORT_NOW:-8000}"
sed -e "s#^Environment=DEFLOW_PORT=.*#Environment=DEFLOW_PORT=${PORT_NOW}#" \
    -e "s#^Environment=PATH=.*#Environment=PATH=${APP_DIR}/bin:${APP_DIR}/.venv/bin:/usr/local/bin:/usr/bin:/bin#" \
    "$APP_DIR/deploy/deflow.service" > /tmp/deflow.service.new
if ! cmp -s /tmp/deflow.service.new /etc/systemd/system/deflow.service; then
  cp /tmp/deflow.service.new /etc/systemd/system/deflow.service
  systemctl daemon-reload
  echo "    unit updated and reloaded"
else
  echo "    unchanged"
fi
rm -f /tmp/deflow.service.new

echo "==> Restarting"
systemctl restart deflow
sleep 4
systemctl is-active --quiet deflow && echo "    deflow is running" || { journalctl -u deflow -n 40 --no-pager; exit 1; }

# Read the port the desk was actually installed on. Hardcoding 8000 meant this
# health check queried whatever else happened to own that port -- on a shared
# host that is someone else's service answering "ok", which is worse than no
# check at all.
PORT=$(grep -E '^DEFLOW_PORT=' "$APP_DIR/.env" | tail -1 | cut -d= -f2 | tr -d ' "')
PORT="${PORT:-8000}"
echo "==> Health on 127.0.0.1:${PORT}"
curl -fsS "127.0.0.1:${PORT}/api/health" && echo
curl -fsS "127.0.0.1:${PORT}/api/ledger/verify" && echo
