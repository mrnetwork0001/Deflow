#!/usr/bin/env bash
# Install Deflow onto a VPS that is ALREADY RUNNING OTHER SERVICES.
#
#   sudo bash install-safe.sh [PORT]      # default port 8000
#
# Contract with the host: this script is strictly additive.
#
#   It does NOT touch the firewall. Enabling ufw with a narrow allow-list is
#     the single fastest way to take down every other service on a box.
#   It does NOT modify or remove any existing nginx site, and adds no
#     default_server -- a second default_server is a config error that stops
#     nginx from reloading at all, taking the existing sites with it.
#   It does NOT bind a public port. The desk listens on 127.0.0.1 only.
#   It does NOT replace an existing Go, Python, or uv installation.
#   It creates exactly one new user, one new systemd unit, and one directory.
#
# Everything it adds is reversible with deploy/uninstall.sh.
#
# The desk trades over outbound HTTPS to Alpaca. It does not need to be
# publicly reachable to make money -- only to be *shown*. So nothing here
# opens a port to the internet; see the notes at the end for viewing it.

set -euo pipefail

PORT="${1:-8000}"
APP_DIR="${APP_DIR:-/opt/deflow}"
REPO=https://github.com/mrnetwork0001/Deflow.git
GO_VERSION=1.24.0

say()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
skip() { printf '    \033[2m· %s\033[0m\n' "$*"; }
warn() { printf '    \033[33m! %s\033[0m\n' "$*"; }

[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }

# ---------------------------------------------------------------------------
say "Pre-flight checks (refusing to proceed if we would collide)"

if ss -ltn 2>/dev/null | grep -q "127.0.0.1:${PORT} \|0.0.0.0:${PORT} \|:::${PORT} "; then
  echo "    ERROR: port ${PORT} is already in use. Re-run with a free port:"
  echo "           sudo bash install-safe.sh 8123"
  exit 1
fi
skip "port ${PORT} is free"

# The directory may legitimately exist without being a checkout: useradd
# --create-home below creates it, so any earlier run that failed after the user
# was added but before the clone leaves a skeleton home behind. Refusing on
# mere existence made the installer un-retryable after its own partial failure.
# Refuse only if it holds files that are not ours.
if [[ -e "$APP_DIR" ]]; then
  if [[ -d "$APP_DIR/.git" ]]; then
    skip "$APP_DIR is an existing Deflow checkout — will update in place"
  else
    STRAY=$(find "$APP_DIR" -mindepth 1 -maxdepth 1 \
              ! -name '.*' ! -name 'data' ! -name 'bin' ! -name '.venv' 2>/dev/null | head -5)
    if [[ -n "$STRAY" ]]; then
      echo "    ERROR: $APP_DIR holds files that are not ours. Refusing to overwrite:"
      echo "$STRAY" | sed 's/^/           /'
      echo "           Move it aside, or install elsewhere with APP_DIR=/opt/deflow2"
      exit 1
    fi
    skip "$APP_DIR exists but holds only a home skeleton — safe to use"
  fi
fi

if systemctl list-unit-files 2>/dev/null | grep -q '^deflow.service'; then
  warn "an existing deflow.service will be replaced (that is ours)"
fi

# ---------------------------------------------------------------------------
say "Installing only the packages that are missing"
MISSING=()
for pkg in git curl python3 python3-venv; do
  dpkg -s "$pkg" &>/dev/null || MISSING+=("$pkg")
done
if ((${#MISSING[@]})); then
  DEBIAN_FRONTEND=noninteractive apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${MISSING[@]}"
  skip "installed: ${MISSING[*]}"
else
  skip "nothing to install"
fi

# ---------------------------------------------------------------------------
say "Creating the deflow service user"
if id -u deflow &>/dev/null; then
  skip "user deflow already exists"
else
  useradd --system --create-home --home-dir "$APP_DIR" --shell /usr/sbin/nologin deflow
  skip "created system user deflow (no shell, no login)"
fi

# ---------------------------------------------------------------------------
say "Fetching the application into $APP_DIR"
if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" fetch --quiet origin main
  git -C "$APP_DIR" reset --hard --quiet origin/main
  skip "updated existing checkout"
else
  # git clone refuses a non-empty directory, and a skeleton home is non-empty
  # (.bashrc, .profile). Clone into a temp path and move the contents across so
  # the existing home, its ownership and any data/ survive.
  TMP_CLONE=$(mktemp -d)
  git clone --quiet "$REPO" "$TMP_CLONE/repo"
  mv "$TMP_CLONE/repo/.git" "$APP_DIR/.git"
  rm -rf "$TMP_CLONE"
  git -C "$APP_DIR" reset --hard --quiet HEAD
  skip "cloned into the existing directory"
fi
mkdir -p "$APP_DIR/data"

# ---------------------------------------------------------------------------
say "Building an isolated Python environment"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
skip "virtualenv at $APP_DIR/.venv — system Python untouched"

# ---------------------------------------------------------------------------
# The Alpaca CLI is the desk's default order route: without it the executor
# falls back to raw REST and loses the CLI's own retry backoff. Installed to
# /opt/deflow/bin so it cannot shadow anything already on the system PATH.
say "Installing Alpaca's official CLI (privately, not system-wide)"
mkdir -p "$APP_DIR/bin"
if [[ -x "$APP_DIR/bin/alpaca" ]]; then
  skip "already present: $("$APP_DIR/bin/alpaca" version 2>/dev/null || echo unknown)"
elif command -v alpaca &>/dev/null; then
  skip "system-wide alpaca found: $(alpaca version 2>/dev/null)"
  ln -sf "$(command -v alpaca)" "$APP_DIR/bin/alpaca"
else
  if command -v go &>/dev/null && go version | grep -qE 'go1\.(2[4-9]|[3-9][0-9])'; then
    skip "using existing $(go version)"
    GOBIN="$APP_DIR/bin" go install github.com/alpacahq/cli/cmd/alpaca@latest
  else
    # Private Go toolchain under /opt/deflow — never /usr/local/go, which may
    # already hold a Go the rest of the box depends on.
    skip "installing a private Go ${GO_VERSION} toolchain (system Go untouched)"
    ARCH=$(dpkg --print-architecture)
    curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-${ARCH}.tar.gz" -o /tmp/deflow-go.tgz
    rm -rf "$APP_DIR/.go" && mkdir -p "$APP_DIR/.go"
    tar -C "$APP_DIR/.go" --strip-components=1 -xzf /tmp/deflow-go.tgz
    rm -f /tmp/deflow-go.tgz
    GOBIN="$APP_DIR/bin" GOPATH="$APP_DIR/.gopath" GOCACHE="$APP_DIR/.gocache" \
      "$APP_DIR/.go/bin/go" install github.com/alpacahq/cli/cmd/alpaca@latest
  fi
fi
"$APP_DIR/bin/alpaca" version 2>/dev/null || warn "alpaca CLI unavailable — the desk will use REST instead"

# ---------------------------------------------------------------------------
say "Installing uv for the Alpaca MCP server (privately)"
if command -v uv &>/dev/null; then
  skip "system uv found: $(uv --version)"
elif [[ -x "$APP_DIR/bin/uv" ]]; then
  skip "already present"
else
  curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR="$APP_DIR/bin" sh >/dev/null 2>&1 || \
    warn "uv install failed — MCP discovery will be unavailable, trading is unaffected"
fi

# ---------------------------------------------------------------------------
say "Writing configuration"
if [[ -f "$APP_DIR/.env" ]]; then
  skip ".env already exists — leaving your keys alone"
else
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  cat >> "$APP_DIR/.env" <<CONF

# --- set by install-safe.sh -------------------------------------------------
# Loopback only. The desk reaches Alpaca outbound; it never needs an open port.
DEFLOW_HOST=127.0.0.1
DEFLOW_PORT=${PORT}
DEFLOW_NO_BOOTSTRAP=1
CONF
  skip "created $APP_DIR/.env from the template"
fi
chmod 600 "$APP_DIR/.env"
chown -R deflow:deflow "$APP_DIR"

# ---------------------------------------------------------------------------
say "Installing the systemd unit"
sed -e "s#^Environment=DEFLOW_PORT=.*#Environment=DEFLOW_PORT=${PORT}#" \
    -e "s#^Environment=PATH=.*#Environment=PATH=${APP_DIR}/bin:${APP_DIR}/.venv/bin:/usr/local/bin:/usr/bin:/bin#" \
    "$APP_DIR/deploy/deflow.service" > /etc/systemd/system/deflow.service
systemctl daemon-reload
systemctl enable deflow >/dev/null 2>&1
skip "deflow.service installed and enabled"

cat <<NEXT

────────────────────────────────────────────────────────────────────────────
  Installed. Nothing else on this server was modified:
    · no firewall rules changed
    · no nginx/apache config touched
    · no system Python, Go or uv replaced
    · listening on 127.0.0.1:${PORT} only — no public port opened

  NEXT — add your keys, then start it:

    sudo nano ${APP_DIR}/.env
        ALPACA_API_KEY=...
        ALPACA_SECRET_KEY=...
        FEATHERLESS_API_KEY=...
        DEFLOW_DRY_RUN=true          <- leave true for the first live cycle

    sudo -u deflow ${APP_DIR}/.venv/bin/python ${APP_DIR}/main.py --check
    sudo systemctl start deflow
    sudo journalctl -u deflow -f

  TO VIEW THE DASHBOARD without opening a port, tunnel from your laptop:

    ssh -N -L 8000:127.0.0.1:${PORT} root@THIS_SERVER
    # then open http://localhost:8000

  PUBLIC URL later, once DNS for your domain resolves here:
    sudo bash ${APP_DIR}/deploy/add-nginx-site.sh usedeflow.xyz ${PORT}

  TO REMOVE EVERYTHING:
    sudo bash ${APP_DIR}/deploy/uninstall.sh
────────────────────────────────────────────────────────────────────────────
NEXT
