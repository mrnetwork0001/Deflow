#!/usr/bin/env bash
# Add a Deflow site to a Caddy that is already serving other sites.
#
#   sudo bash add-caddy-site.sh usedeflow.xyz 8090
#
# Caddy, not nginx, is the reverse proxy on hosts where it holds :80 and :443.
# Trying to serve Deflow from nginx on such a box either fails to bind or --
# worse -- starts fighting Caddy for the ports once someone repairs nginx.
#
# Additive only: appends one site block to the Caddyfile, backs it up first,
# validates the WHOLE config before reloading, and restores the backup if
# validation fails. Caddy provisions its own certificate, so there is no
# certbot step and no renewal cron to forget.

set -euo pipefail

DOMAIN="${1:?usage: add-caddy-site.sh DOMAIN [PORT]}"
PORT="${2:-8090}"
CADDYFILE="${CADDYFILE:-/etc/caddy/Caddyfile}"

say()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '    \033[33m! %s\033[0m\n' "$*"; }

[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
command -v caddy >/dev/null || { echo "caddy is not installed"; exit 1; }
[[ -f "$CADDYFILE" ]] || { echo "no Caddyfile at $CADDYFILE (set CADDYFILE=...)"; exit 1; }

say "Checking for collisions"
if grep -qE "^\s*(https?://)?(www\.)?${DOMAIN//./\\.}\b" "$CADDYFILE"; then
  echo "    ERROR: ${DOMAIN} already appears in ${CADDYFILE}. Refusing to double-declare."
  grep -nE "^\s*(https?://)?(www\.)?${DOMAIN//./\\.}\b" "$CADDYFILE" | sed 's/^/           /'
  exit 1
fi
printf '    · %s is unclaimed\n' "$DOMAIN"

BACKUP="${CADDYFILE}.bak-$(date +%Y%m%d-%H%M%S)"
cp -a "$CADDYFILE" "$BACKUP"
printf '    · backed up to %s\n' "$BACKUP"

say "Appending the Deflow site block"
cat >> "$CADDYFILE" <<CONF

# ── Deflow — autonomous options desk ────────────────────────────────────────
# Added by deploy/add-caddy-site.sh. Caddy obtains and renews the certificate
# automatically; there is no certbot step here.
${DOMAIN}, www.${DOMAIN} {
	encode gzip

	header {
		X-Content-Type-Options nosniff
		X-Frame-Options SAMEORIGIN
		Referrer-Policy strict-origin-when-cross-origin
	}

	# Server-sent events. flush_interval -1 disables response buffering: with
	# it buffered, the decision stream is held by the proxy and released in
	# bursts, so the dashboard looks frozen between trading cycles.
	@stream path /api/stream
	reverse_proxy @stream 127.0.0.1:${PORT} {
		flush_interval -1
		transport http {
			read_timeout 24h
		}
	}

	reverse_proxy 127.0.0.1:${PORT}
}
CONF

say "Validating the entire Caddy config (your other sites included)"
if ! caddy validate --config "$CADDYFILE" --adapter caddyfile 2>&1 | tail -5; then
  warn "validation failed — restoring your original Caddyfile, nothing changed"
  cp -a "$BACKUP" "$CADDYFILE"
  exit 1
fi

say "Reloading Caddy (zero-downtime; existing sites keep serving)"
if ! systemctl reload caddy; then
  warn "reload failed — restoring backup"
  cp -a "$BACKUP" "$CADDYFILE"
  systemctl reload caddy || true
  exit 1
fi
printf '    · reloaded\n'

cat <<NEXT

  https://${DOMAIN}/ will serve Deflow as soon as Caddy finishes issuing the
  certificate (usually seconds; watch with: journalctl -u caddy -f).

  Allow the browser origin so the dashboard can call its own API:
      echo "DEFLOW_CORS_ORIGINS=https://${DOMAIN},https://www.${DOMAIN}" >> /opt/deflow/.env
      systemctl restart deflow

  Rollback:  cp ${BACKUP} ${CADDYFILE} && systemctl reload caddy
NEXT
