#!/usr/bin/env bash
# READ-ONLY inspection of a shared VPS. Changes nothing, installs nothing.
#
#   bash preflight.sh
#
# Run this before provisioning. Deflow is going onto a host that is already
# doing useful work, and the install has to route around whatever is there --
# not assume an empty machine.

set -uo pipefail

hdr() { printf '\n\033[1;36m── %s \033[0m%s\n' "$1" "$(printf '─%.0s' $(seq 1 $((60 - ${#1}))))"; }
ok()  { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn(){ printf '  \033[33m!\033[0m %s\n' "$*"; }
info(){ printf '    %s\n' "$*"; }

hdr "Host"
info "$(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" || uname -sr)"
info "kernel $(uname -r)  |  $(nproc) cpu  |  $(free -h 2>/dev/null | awk '/Mem:/{print $2" ram, "$7" available"}')"
info "disk: $(df -h / | awk 'NR==2{print $4" free of "$2}')"

hdr "Ports already in use"
if command -v ss >/dev/null; then
  ss -ltnp 2>/dev/null | awk 'NR>1{split($4,a,":"); print a[length(a)]"\t"$6}' \
    | sed 's/users:((//; s/))//' | sort -n -u | while read -r port proc; do
      printf '    %-7s %s\n' "$port" "$proc"
    done
else
  warn "ss not available"
fi

hdr "Is port 8000 free?"
if ss -ltn 2>/dev/null | grep -q ':8000 '; then
  warn "PORT 8000 IS TAKEN — Deflow must use another port"
  ss -ltnp 2>/dev/null | grep ':8000 ' | sed 's/^/    /'
else
  ok "8000 is free"
fi

hdr "Web server"
for svc in nginx apache2 caddy; do
  if systemctl list-unit-files 2>/dev/null | grep -q "^${svc}.service"; then
    state=$(systemctl is-active "$svc" 2>/dev/null)
    ok "$svc present and $state"
    if [[ $svc == nginx ]]; then
      info "existing sites-enabled:"
      ls -1 /etc/nginx/sites-enabled/ 2>/dev/null | sed 's/^/      /' || info "      (none)"
      info "existing default_server declarations:"
      grep -rl "default_server" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | sed 's/^/      /' || info "      (none)"
      info "server_names already claimed:"
      grep -rhoP '(?<=server_name\s)[^;]+' /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null \
        | tr ' ' '\n' | grep -v '^$' | sort -u | sed 's/^/      /' || info "      (none)"
    fi
  fi
done
command -v nginx apache2 caddy >/dev/null 2>&1 || warn "no web server installed — Deflow can run without one"

hdr "Firewall"
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
  warn "ufw is ACTIVE — do not re-run 'ufw enable'; existing rules:"
  ufw status numbered 2>/dev/null | sed 's/^/    /'
elif command -v ufw >/dev/null; then
  info "ufw installed but inactive — leave it that way"
else
  info "ufw not installed"
fi
if command -v iptables >/dev/null; then
  n=$(iptables -S 2>/dev/null | wc -l)
  info "iptables rules present: $n"
fi

hdr "Toolchain already installed"
for c in python3 git go uv docker certbot; do
  if command -v "$c" >/dev/null; then ok "$c $(${c} --version 2>&1 | head -1)"; else info "$c: not installed"; fi
done

hdr "Users and existing services"
info "non-system users: $(awk -F: '$3>=1000 && $3<65534 {print $1}' /etc/passwd | tr '\n' ' ')"
info "running services (non-default):"
systemctl list-units --type=service --state=running --no-legend --no-pager 2>/dev/null \
  | awk '{print $1}' \
  | grep -vE '^(systemd|dbus|cron|ssh|rsyslog|networkd|resolved|logind|udev|getty|polkit|snapd|unattended|multipathd|accounts|apparmor)' \
  | sed 's/^/      /'

hdr "Verdict"
echo "    Send this whole output back. Nothing was changed."
