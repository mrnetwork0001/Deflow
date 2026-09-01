# Deploying Deflow

The desk is a **long-running process**, not a request handler. It holds a scheduler thread, marks
the book every cycle, shells out to Alpaca's CLI, and appends to a hash chain on disk. That rules
out serverless hosting for the backend — a Vercel function cannot keep a trading loop alive, keep a
ledger, or run a Go binary.

**The desk does not need to be publicly reachable to trade.** It reaches Alpaca over outbound
HTTPS. A public URL is for *showing* it, not for running it — so nothing here opens a port, and
DNS is never on the critical path to placing a trade.

---

## Installing on a VPS that already runs other services

This is the supported path, and it is **strictly additive**. It does not touch the firewall, does
not modify or remove any existing nginx site, does not replace a system Python, Go or uv, and does
not bind a public port.

### 1. Look before you touch

```bash
sudo bash deploy/preflight.sh
```

Read-only. Reports which ports are in use, which nginx sites and `server_name`s already exist,
whether a firewall is active, and what is already installed. Nothing is changed.

### 2. Install

```bash
sudo bash deploy/install-safe.sh          # or: install-safe.sh 8123 for a different port
```

It refuses to continue if the port is taken or if `/opt/deflow` exists and is not a Deflow
checkout. Everything it adds lives under `/opt/deflow`: a virtualenv, a private Go toolchain if
the system has none new enough, the Alpaca CLI in `/opt/deflow/bin`, one system user, and one
systemd unit.

### 3. Configure and start

```bash
sudo nano /opt/deflow/.env      # the three API keys; keep DEFLOW_DRY_RUN=true for the first cycle
sudo -u deflow /opt/deflow/.venv/bin/python /opt/deflow/main.py --check
sudo systemctl start deflow
sudo journalctl -u deflow -f
```

### 4. View it without opening a port

```bash
ssh -N -L 8000:127.0.0.1:8000 root@YOUR_VPS     # from your laptop
# then browse http://localhost:8000
```

### 5. Public URL, once DNS resolves

```bash
sudo bash deploy/add-nginx-site.sh usedeflow.xyz 8000
sudo certbot --nginx -d usedeflow.xyz -d www.usedeflow.xyz
echo "DEFLOW_CORS_ORIGINS=https://usedeflow.xyz,https://www.usedeflow.xyz" | sudo tee -a /opt/deflow/.env
sudo systemctl restart deflow
```

`add-nginx-site.sh` writes one new vhost, backs up `/etc/nginx` first, declares **no
`default_server`** (a second one stops nginx starting at all, taking every other site with it),
refuses to run if the domain is already claimed, and rolls itself back if `nginx -t` fails.

### Updating and removing

```bash
sudo bash /opt/deflow/deploy/update.sh       # pull + restart; never touches data/
sudo bash /opt/deflow/deploy/uninstall.sh    # removes everything, keeps the ledger
```

---

## Alternative: Docker

```bash
docker compose up --build        # reads .env, publishes on :8090
```

`fly.toml` and `render.yaml` are included and tested. Both pin **one instance**: a second replica
would append to the same ledger and submit every order twice.

---

## Alternative: Vercel front end, VPS backend

Only worth it if you want a CDN. It adds a second origin and therefore CORS.

1. Vercel → import the repo → **Root Directory: `web`**. `web/vercel.json` handles the rest.
2. Set `NEXT_PUBLIC_API_BASE=https://api.usedeflow.xyz`.
3. Point `api.usedeflow.xyz` at the VPS and add that vhost with `add-nginx-site.sh`.
4. Add the front-end origin to `DEFLOW_CORS_ORIGINS`.

Origins are listed explicitly rather than wildcarded — `POST /api/cycle` and
`POST /api/risk/evaluate` cause work, so a wildcard would let any page on the internet drive the
desk. Vercel preview subdomains are admitted by regex.

---

## Operational notes

- **Never run two instances against one data directory.** The ledger takes a cross-process lock so
  the chain survives it, but both would independently submit orders.
- **Back up `data/ledger.jsonl`.** It is the artefact that makes the P&L checkable.
- **`DEFLOW_DRY_RUN=true`** renders orders without submitting — use it for the first live cycle on
  a new host, then switch it off.
- **The desk is paper-only by construction**: the REST client refuses a non-paper endpoint, the CLI
  bridge pins `ALPACA_LIVE_TRADE=false`, and the MCP client pins `ALPACA_PAPER_TRADE=true`.
- **Kill switch:** `sudo systemctl stop deflow`. Breaker 11 also halts new risk automatically at
  −3% on the session.
