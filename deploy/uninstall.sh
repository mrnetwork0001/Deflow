#!/usr/bin/env bash
# Remove Deflow completely, leaving every other service on the host untouched.
#
#   sudo bash uninstall.sh [--purge-data]
#
# Without --purge-data the ledger and position book are preserved: the hash
# chain is the record of what the desk actually did, and it should outlive the
# software that wrote it.

set -euo pipefail
APP_DIR=/opt/deflow
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }

echo "==> Stopping the service"
systemctl stop deflow 2>/dev/null || true
systemctl disable deflow 2>/dev/null || true
rm -f /etc/systemd/system/deflow.service
systemctl daemon-reload

echo "==> Removing the nginx vhost (ours only)"
rm -f /etc/nginx/sites-enabled/deflow /etc/nginx/sites-available/deflow
if command -v nginx >/dev/null && nginx -t 2>/dev/null; then
  systemctl reload nginx
  echo "    nginx reloaded; other sites unaffected"
fi

if [[ "${1:-}" == "--purge-data" ]]; then
  echo "==> Removing $APP_DIR including the ledger"
  rm -rf "$APP_DIR"
  userdel deflow 2>/dev/null || true
else
  echo "==> Preserving $APP_DIR/data (ledger + positions)"
  find "$APP_DIR" -mindepth 1 -maxdepth 1 ! -name data -exec rm -rf {} + 2>/dev/null || true
  echo "    re-run with --purge-data to remove it too"
fi

echo "==> Done. No firewall, Python, Go or other nginx site was modified."
