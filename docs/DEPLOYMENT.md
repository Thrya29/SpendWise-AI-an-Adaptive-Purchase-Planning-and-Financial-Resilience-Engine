# Deploying SpendWise

One server running Docker Compose: PostgreSQL, Redis, the API, the background worker, the web
app and (for a public site) Caddy for HTTPS. CI builds exactly this stack on every push, runs
an end-to-end test on a phone-sized browser against it, load tests it, and backs it up and
restores it.

## 1. Server

* 2 vCPU and 4 GB RAM are enough for a pilot or a small community. The planner is the CPU-heavy
  part; see [planner scaling](results/planner-scaling.md).
* Ubuntu 24.04 LTS (or any Linux with Docker Engine 24+ and the Compose plugin).
* A DNS A/AAAA record for your domain pointing at the server, and ports 80 and 443 open.
  Keep every other port closed (`ufw allow 22,80,443/tcp`).

## 2. First start

```bash
git clone https://github.com/Thrya29/SpendWise-AI-an-Adaptive-Purchase-Planning-and-Financial-Resilience-Engine.git /opt/spendwise
cd /opt/spendwise
python3 scripts/generate_env.py          # random database password, JWT secret, encryption key
```

Edit `.env`:

| Setting | Value |
|---|---|
| `DOMAIN` | your hostname, e.g. `money.example.org` (add this line) |
| `SPENDWISE_APP_URL` | `https://money.example.org` (links in emails) |
| `SPENDWISE_SMTP_*` | optional, for email reminders (any SMTP provider; port 587 = STARTTLS) |

Then:

```bash
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build --wait
```

Caddy obtains a certificate on first request and renews it automatically. It adds HSTS. The
API, database and Redis are never published; only Caddy listens publicly. The API applies
database migrations as it starts.

Without a domain (a private machine or LAN), use `docker compose up -d --build --wait` and open
`http://localhost:3000`.

**Keep `.env` safe and backed up separately.** `SPENDWISE_ENCRYPTION_KEY` decrypts users' stored
Claude API keys. If you lose it, those keys must be re-entered; never change it on a running
system.

## 3. Backups

```bash
scripts/backup.sh                       # writes backups/spendwise-<UTC time>.sql.gz, keeps 14
crontab -e                               # daily at 02:15:
# 15 2 * * *  cd /opt/spendwise && scripts/backup.sh >> backups/backup.log 2>&1
```

Copy `backups/` off the server as well (for example `rclone copy backups remote:spendwise`).
A backup on the same disk does not survive losing the server. Backups contain personal
financial data, so store them encrypted and with restricted access. `backups/` is git-ignored.

Test a restore every few months without touching live data:

```bash
scripts/restore.sh backups/spendwise-<time>.sql.gz --into restore_check
docker compose exec db psql -U spendwise -d restore_check -c 'select count(*) from users'
docker compose exec db dropdb -U spendwise restore_check
```

To replace the live database (this stops the API and worker during the restore):

```bash
scripts/restore.sh backups/spendwise-<time>.sql.gz --yes
```

## 4. Updates and rollback

```bash
scripts/backup.sh
git pull
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build --wait
```

Migrations run automatically and only move forward. To roll back: check out the previous
commit, restore the backup taken before the update, and start again with the command above.

## 5. Monitoring

| What | How |
|---|---|
| Is it up? | `curl -fsS https://<domain>/login` (web), and inside the stack `GET /readyz` checks PostgreSQL and Redis (503 if either is down) |
| Container health | `docker compose ps`. The database, Redis, API, worker and web have health checks; the worker is healthy while its loop has completed a cycle in the last 10 minutes |
| Logs | `docker compose logs -f api worker`. JSON lines with `request_id`, `path`, `status` and `duration_ms` |
| Slow requests | lines with `"message": "slow_request"` (over 1 s) |
| Errors | `unhandled_error` (API), `worker_cycle_failed`, `notify_failed`, `digest_failed` (worker) |
| Data sources | `amfi_refresh_failed`, `gold_refresh_failed` and FX warnings. The app keeps showing the last good data with its date |
| Usage (pilot) | `docker compose exec -T api python -m app.pilot_report > pilot-report.md` |

Any log shipper that reads Docker's JSON logs (Loki, Grafana Agent, Vector, CloudWatch) can alert
on these messages. An uptime checker hitting `/login` covers the rest.

## 6. Load

`backend/scripts/loadtest.py` drives a running deployment through its public URL. It uses test
accounts that each have a salary, bills and 12 items, and repeats the dashboard, item list,
alert count and planner calls. CI runs it for 45 seconds against the Compose stack and shows the
results in the run summary.

```bash
python backend/scripts/loadtest.py --base https://<domain> --users 4 --concurrency 8 --seconds 60
```

It creates accounts, so only point it at a deployment you own. A plan is limited to 30 runs per
user per minute (429 beyond that). Uploads are capped at 1 MB, or 3.5 MB for bank statements,
by both the web proxy and the API.

## 7. Security checklist

- [ ] `.env` generated by `scripts/generate_env.py`, readable only by root (`chmod 600 .env`)
- [ ] Only ports 22, 80 and 443 open; SSH with keys, password login disabled
- [ ] HTTPS through Caddy (HSTS on); `SPENDWISE_COOKIE_SECURE=true`
- [ ] Daily backups copied off the server, and a restore tested
- [ ] OS security updates enabled (`unattended-upgrades`)
- [ ] `git pull` regularly; CI runs `pip-audit` and `npm audit` on every change

See [SECURITY.md](SECURITY.md) for the controls built into the application.
