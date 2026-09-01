# Deploying Deflow

The desk is a **long-running process**, not a request handler. It holds a scheduler thread, marks
the book every cycle, shells out to Alpaca's CLI, and appends to a hash chain on disk. That rules
out serverless hosting for the backend — a Vercel function cannot keep a trading loop alive, keep a
ledger, or run a Go binary.

So there are two shapes. **Option A is recommended** and is what `usedeflow.xyz` uses.

---

## Option A — everything on one VPS (recommended)

```
usedeflow.xyz ──▶ nginx ──▶ FastAPI :8000 ──▶ site + API + trading loop
                                    └──▶ /opt/deflow/data (ledger, positions)
```

One origin, so **no CORS**, one process to supervise, and the ledger lives on a real disk.

```bash
ssh root@YOUR_VPS
curl -fsSL https://raw.githubusercontent.com/mrnetwork0001/Deflow/main/deploy/provision.sh \
  | bash -s -- usedeflow.xyz
```

That installs nginx, Python, **Alpaca's official CLI** (Go 1.24 — the CLI will not build on 1.23),
`uv` for the MCP server, a hardened `systemd` unit, and a firewall. It stops before touching your
keys.

Then, on the server:

```bash
nano /opt/deflow/.env          # ALPACA_API_KEY, ALPACA_SECRET_KEY, FEATHERLESS_API_KEY
                               # leave DEFLOW_DRY_RUN=false so it actually trades
```

**DNS** — at Namecheap, set two A records to your VPS IP:

| Type | Host | Value |
|---|---|---|
| A | `@` | `YOUR_VPS_IP` |
| A | `www` | `YOUR_VPS_IP` |

Once DNS resolves:

```bash
certbot --nginx -d usedeflow.xyz -d www.usedeflow.xyz
systemctl start deflow
journalctl -u deflow -f
```

Verify:

```bash
/opt/deflow/.venv/bin/python /opt/deflow/main.py --check   # every integration
curl -s localhost:8000/api/health
curl -s localhost:8000/api/ledger/verify                   # chain must be intact
```

To ship a change: `git push`, then `/opt/deflow/deploy/update.sh` on the server. It never touches
`data/`.

---

## Option B — Vercel front end, VPS backend

Only worth it if you want the CDN. It adds a second origin and therefore CORS.

1. Vercel → import the repo → **Root Directory: `web`**. `web/vercel.json` handles the rest.
2. Set `NEXT_PUBLIC_API_BASE=https://api.usedeflow.xyz` in Vercel's environment variables.
3. Point `api.usedeflow.xyz` at the VPS and run Option A's provisioning for that subdomain.
4. On the VPS, add the front end to the allowed origins:

```bash
DEFLOW_CORS_ORIGINS=https://usedeflow.xyz,https://www.usedeflow.xyz
```

Origins are listed explicitly rather than wildcarded — `POST /api/cycle` and
`POST /api/risk/evaluate` cause work, so a wildcard would let any page on the internet drive the
desk. Vercel preview subdomains are admitted by regex.

---

## Option C — Docker

```bash
docker compose up --build        # reads .env, publishes on :8090
```

`fly.toml` and `render.yaml` are included and tested. Both pin **one instance**: a second replica
would append to the same ledger and submit every order twice.

---

## Operational notes

- **Never run two instances against one data directory.** The ledger takes a cross-process lock so
  the chain survives it, but both would independently submit orders.
- **Back up `data/ledger.jsonl`.** It is the artefact that makes the P&L checkable.
- **`DEFLOW_DRY_RUN=true`** renders orders without submitting — use it to smoke-test a new host
  during market hours without taking positions.
- **The desk is paper-only by construction**: the REST client refuses a non-paper endpoint, the CLI
  bridge pins `ALPACA_LIVE_TRADE=false`, and the MCP client pins `ALPACA_PAPER_TRADE=true`.
