#!/usr/bin/env bash
# Add a Deflow vhost to an nginx that is already serving other sites.
#
#   sudo bash add-nginx-site.sh usedeflow.xyz 8000
#
# Additive only. It writes ONE new file, symlinks it, and reloads. It never
# edits or removes an existing site, and it declares no default_server --
# a second default_server makes nginx refuse to start, which would take every
# other site on the box down with it.
#
# Requires DNS for the domain to already point at this server, because certbot
# validates over HTTP.

set -euo pipefail

DOMAIN="${1:?usage: add-nginx-site.sh DOMAIN [PORT]}"
PORT="${2:-8000}"
SITE=/etc/nginx/sites-available/deflow

say()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '    \033[33m! %s\033[0m\n' "$*"; }

[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
command -v nginx >/dev/null || { echo "nginx is not installed"; exit 1; }

say "Checking for collisions"
if grep -rq "server_name.*\b${DOMAIN}\b" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null; then
  # Only our own file may already claim it.
  if ! grep -q "server_name.*\b${DOMAIN}\b" "$SITE" 2>/dev/null; then
    echo "    ERROR: ${DOMAIN} is already served by another nginx site. Refusing."
    grep -rl "server_name.*\b${DOMAIN}\b" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | sed 's/^/           /'
    exit 1
  fi
fi
printf '    · %s is unclaimed\n' "$DOMAIN"

say "Backing up current nginx state"
BACKUP=/root/nginx-backup-$(date +%Y%m%d-%H%M%S).tar.gz
tar czf "$BACKUP" /etc/nginx 2>/dev/null || true
printf '    · %s\n' "$BACKUP"

say "Writing the Deflow vhost"
cat > "$SITE" <<CONF
# Deflow — added by deploy/add-nginx-site.sh. Name-based only; no
# default_server, so this cannot capture traffic meant for other sites.
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN} www.${DOMAIN};

    location /.well-known/acme-challenge/ { root /var/www/html; }

    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options SAMEORIGIN always;

    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;
    gzip_min_length 1024;
    client_max_body_size 2m;

    # Server-sent events. Buffering here would hold the decision stream inside
    # nginx and release it in bursts, so the dashboard would look frozen
    # between cycles; the long read timeout keeps it open across quiet gaps.
    location /api/stream {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 24h;
        chunked_transfer_encoding on;
    }

    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_http_version 1.1;
        proxy_set_header Host              \$host;
        proxy_set_header X-Real-IP         \$remote_addr;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Connection        "";
        proxy_read_timeout 120s;
    }
}
CONF
ln -sf "$SITE" /etc/nginx/sites-enabled/deflow

say "Validating the FULL nginx config (yours included)"
if ! nginx -t; then
  warn "config test failed — rolling back, your other sites are untouched"
  rm -f /etc/nginx/sites-enabled/deflow
  nginx -t && systemctl reload nginx
  exit 1
fi

systemctl reload nginx
printf '    · reloaded; existing sites unaffected\n'

cat <<NEXT

  http://${DOMAIN}/ should now serve Deflow.

  For HTTPS (certbot only edits the deflow vhost when given -d for it):
      sudo certbot --nginx -d ${DOMAIN} -d www.${DOMAIN}

  Then allow the browser origin, so the dashboard can call its own API:
      echo "DEFLOW_CORS_ORIGINS=https://${DOMAIN},https://www.${DOMAIN}" >> /opt/deflow/.env
      sudo systemctl restart deflow

  Rollback:  rm /etc/nginx/sites-enabled/deflow && nginx -t && systemctl reload nginx
  Backup:    ${BACKUP}
NEXT
