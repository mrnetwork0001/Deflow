#!/usr/bin/env bash
# Provision a fresh Ubuntu/Debian VPS to run the Deflow desk at usedeflow.xyz.
#
#   ssh root@YOUR_VPS
#   curl -fsSL https://raw.githubusercontent.com/mrnetwork0001/Deflow/main/deploy/provision.sh | bash -s -- usedeflow.xyz
#
# Idempotent: safe to re-run. It does NOT write your API keys — it creates
# /opt/deflow/.env from the template and stops so you can paste them in.

set -euo pipefail

# Pass a domain to configure it, or "ip" to deploy without DNS. DNS and TLS
# are needed for a presentable URL, not for the desk to trade -- so a registrar
# outage should never be what stops an agent being live at the market open.
DOMAIN="${1:-ip}"
APP_DIR=/opt/deflow
REPO=https://github.com/mrnetwork0001/Deflow.git
GO_VERSION=1.24.0

say() { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }

[[ $EUID -eq 0 ]] || { echo "run as root"; exit 1; }

say "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl nginx python3 python3-venv python3-pip \
                      certbot python3-certbot-nginx ufw >/dev/null

say "Creating the deflow service user"
id -u deflow &>/dev/null || useradd --system --create-home --home-dir "$APP_DIR" --shell /usr/sbin/nologin deflow

say "Fetching the application"
if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" fetch --quiet origin main && git -C "$APP_DIR" reset --hard --quiet origin/main
else
  git clone --quiet "$REPO" "$APP_DIR"
fi
mkdir -p "$APP_DIR/data"

say "Building the Python environment"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

# The Alpaca CLI is the desk's default order route. Without it the executor
# silently falls back to raw REST and loses the CLI's own retry backoff, so
# this is not optional tooling.
say "Installing Alpaca's official CLI"
if ! command -v alpaca &>/dev/null; then
  ARCH=$(dpkg --print-architecture)
  curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-${ARCH}.tar.gz" -o /tmp/go.tgz
  rm -rf /usr/local/go && tar -C /usr/local -xzf /tmp/go.tgz && rm /tmp/go.tgz
  GOBIN=/usr/local/bin /usr/local/go/bin/go install github.com/alpacahq/cli/cmd/alpaca@latest
fi
alpaca version || true

say "Installing uv (for the Alpaca MCP server)"
command -v uv &>/dev/null || { curl -LsSf https://astral.sh/uv/install.sh | sh; install -m755 ~/.local/bin/uv /usr/local/bin/uv 2>/dev/null || true; }

say "Preparing configuration"
if [[ ! -f "$APP_DIR/.env" ]]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  # Same-origin deployment: nginx fronts both the site and the API, so no CORS.
  {
    echo
    echo "DEFLOW_HOST=127.0.0.1"
    echo "DEFLOW_PORT=8000"
    if [[ "$DOMAIN" != "ip" ]]; then
      echo "DEFLOW_CORS_ORIGINS=https://${DOMAIN},https://www.${DOMAIN}"
    fi
    echo "DEFLOW_NO_BOOTSTRAP=1"
  } >> "$APP_DIR/.env"
fi
chmod 600 "$APP_DIR/.env"
chown -R deflow:deflow "$APP_DIR"

say "Installing the service"
cp "$APP_DIR/deploy/deflow.service" /etc/systemd/system/deflow.service
systemctl daemon-reload
systemctl enable deflow >/dev/null

if [[ "$DOMAIN" == "ip" ]]; then
  say "Configuring nginx for direct IP access (no DNS yet)"
  cp "$APP_DIR/deploy/nginx-ip.conf" /etc/nginx/sites-available/deflow
else
  say "Configuring nginx for ${DOMAIN}"
  sed "s/usedeflow\.xyz/${DOMAIN}/g" "$APP_DIR/deploy/nginx.conf" > /etc/nginx/sites-available/deflow
fi
ln -sf /etc/nginx/sites-available/deflow /etc/nginx/sites-enabled/deflow
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

SERVER_IP=$(curl -fsS https://api.ipify.org 2>/dev/null || echo YOUR_IP)

say "Firewall"
ufw allow OpenSSH >/dev/null 2>&1 || true
ufw allow 'Nginx Full' >/dev/null 2>&1 || true
ufw --force enable >/dev/null 2>&1 || true

cat <<NEXT

────────────────────────────────────────────────────────────────────────
  Provisioned. Two steps left, both yours:

  1. Add your keys:
       nano ${APP_DIR}/.env
     Set ALPACA_API_KEY, ALPACA_SECRET_KEY, FEATHERLESS_API_KEY.
     Leave DEFLOW_DRY_RUN=false so the desk actually trades.

  2. Start trading — this does NOT need DNS or a certificate:
       systemctl start deflow
       journalctl -u deflow -f
     The dashboard is then live at  http://${SERVER_IP}/

  3. Later, when your registrar is available, point the domain here
     (A records @ and www -> ${SERVER_IP}), wait for DNS, then:
       cp ${APP_DIR}/deploy/nginx.conf /etc/nginx/sites-available/deflow
       sed -i "s/usedeflow.xyz/YOUR_DOMAIN/g" /etc/nginx/sites-available/deflow
       nginx -t && systemctl reload nginx
       certbot --nginx -d YOUR_DOMAIN -d www.YOUR_DOMAIN
     No restart of the desk is required — nginx is in front of it.

  Verify:
       curl -s localhost:8000/api/health
       ${APP_DIR}/.venv/bin/python ${APP_DIR}/main.py --check
────────────────────────────────────────────────────────────────────────
NEXT
