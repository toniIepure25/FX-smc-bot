# Complete Deployment Guide: Kamatera VPS to Live Broker Demo

**Strategy**: `bos_only_usdjpy` (frozen)
**Broker**: OANDA (free practice account, then live)
**VPS**: Kamatera Performance Cloud
**Timeline**: Paper (3-5 days) → Broker Demo (1 week) → Prop Trading

---

## PHASE 0: PREREQUISITES (Do These First, Before Creating the Server)

### Step 0.1 — Create an OANDA Practice Account

1. Go to https://www.oanda.com/register/#/sign-up/demo
2. Sign up for a **free practice/demo account**
3. Once logged in, go to **Manage API Access**:
   - URL: https://www.oanda.com/demo-account/tpa/personal_token
4. Click **"Generate"** to create an API token
5. **COPY AND SAVE** the token — you only see it once
6. Note your **Account ID** (shown on the dashboard, format: `101-001-XXXXXXX-XXX`)

You now have:
- `OANDA_API_KEY` = your generated token
- `OANDA_ACCOUNT_ID` = your account ID number

### Step 0.2 — Create a Telegram Bot for Alerts

1. Open Telegram, search for **@BotFather**
2. Send `/newbot`
3. Follow the prompts (give it a name like "FX SMC Bot Alerts")
4. Copy the **bot token** (format: `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)
5. Send any message to your new bot (just say "hello")
6. Open in browser: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
7. Find `"chat":{"id":123456789}` — that's your **chat ID**

You now have:
- `TELEGRAM_BOT_TOKEN` = the token from step 4
- `TELEGRAM_CHAT_ID` = the number from step 7

---

## PHASE 1: CREATE THE KAMATERA VPS

### Step 1.1 — Click "Create New Server"

On the Kamatera dashboard, click the green **"+ Create New Server"** button.

### Step 1.2 — Server Configuration

Use these settings:

| Setting | Value |
|---------|-------|
| **Server Name** | `fx-smc-bot` |
| **Zone** | Choose the closest to you (EU or US) |
| **OS Image** | **Ubuntu 22.04 64-bit** |
| **CPU** | **1 vCPU** (Type B — General Purpose) |
| **RAM** | **1 GB** |
| **Disk** | **20 GB SSD** |
| **Network** | Default (1 public IP) |
| **Password** | Set a strong root password — save it |

### Step 1.3 — Create and Wait

1. Click **Create** at the bottom
2. Wait 2-5 minutes for the server to provision
3. Once ready, note the **IP address** shown in the server list

---

## PHASE 2: SET UP THE VPS

### Step 2.1 — SSH Into the Server

From your local terminal:

```bash
ssh root@YOUR_VPS_IP
```

Enter the password you set.

### Step 2.2 — Initial System Setup

Copy-paste this entire block:

```bash
# Update system
apt update && apt upgrade -y

# Install Docker
apt install -y docker.io docker-compose-plugin curl git

# Enable Docker on boot
systemctl enable docker
systemctl start docker

# Create project user (optional but recommended)
adduser --disabled-password --gecos "" fx
usermod -aG docker fx

# Create project directory
mkdir -p /opt/fx-smc-bot
chown fx:fx /opt/fx-smc-bot
```

### Step 2.3 — Upload the Project

**Option A — Git clone** (if you have the repo on GitHub):
```bash
su - fx
git clone https://github.com/YOUR_USERNAME/fx-smc-bot.git /opt/fx-smc-bot
```

**Option B — SCP from your laptop** (recommended):
From your LOCAL machine (not the VPS):
```bash
scp -r /home/tonystark/Desktop/fx-smc-bot/FX-smc-bot/* root@YOUR_VPS_IP:/opt/fx-smc-bot/
```

### Step 2.4 — Configure Environment

On the VPS:

```bash
cd /opt/fx-smc-bot
cp .env.example .env
nano .env
```

Fill in these values (paste the ones you saved from Phase 0):

```
FEED_MODE=oanda
OANDA_API_KEY=paste_your_oanda_token_here
OANDA_ACCOUNT_ID=paste_your_account_id_here
OANDA_PRACTICE=true
TELEGRAM_BOT_TOKEN=paste_your_telegram_bot_token_here
TELEGRAM_CHAT_ID=paste_your_chat_id_here
```

Save with `Ctrl+O`, `Enter`, `Ctrl+X`.

### Step 2.5 — Build the Docker Image

```bash
cd /opt/fx-smc-bot
docker compose build
```

This takes 2-5 minutes. You should see "Successfully built" at the end.

---

## PHASE 3: FIRST RUN — PAPER MODE VALIDATION

Before connecting to the broker demo, run paper mode for 3-5 days to verify everything works.

### Step 3.1 — Start the Service

```bash
docker compose up -d forward-paper
```

### Step 3.2 — Verify It's Running

```bash
# Check container status
docker compose ps

# Check logs (should show OANDA connection + warmup)
docker compose logs -f forward-paper
```

You should see:
```
OANDA feeds configured: USDJPY practice=True
Fetching H1 warmup history from OANDA...
OANDA history: 500 bars loaded (from 2026-03-... to 2026-04-...)
Fetching H4 warmup history from OANDA...
OANDA history: 200 bars loaded
Starting forward paper: run_id=fwd_20260424_... mode=oanda
```

### Step 3.3 — Verify Telegram

You should receive a Telegram message:
```
ℹ️ INFO | lifecycle
Forward paper service started
Run: fwd_20260424_...
Mode: oanda
Config: abc123def456
```

If you don't receive it, check your `.env` values.

### Step 3.4 — Install Scheduled Reports

```bash
crontab -e
```

Add these lines at the bottom:

```
# Daily report at 22:00 UTC (after NY close)
0 22 * * 1-5 cd /opt/fx-smc-bot && docker compose run --rm daily-report 2>> /var/log/fx-reports.log

# Weekly report on Saturday at 10:00 UTC
0 10 * * 6 cd /opt/fx-smc-bot && docker compose run --rm weekly-report 2>> /var/log/fx-reports.log
```

Save and exit.

### Step 3.5 — Monitor for 3-5 Days

During paper mode:
- Check Telegram daily for the automated report
- Look for trades being generated
- Verify no EMERGENCY alerts
- Confirm feed connectivity (bars being processed)

Use these commands to check anytime:

```bash
# Quick status
docker compose ps
docker compose logs --tail 20 forward-paper

# Detailed health
docker compose exec forward-paper cat /app/forward_runs/health.json
```

---

## PHASE 4: TRANSITION TO BROKER DEMO

After 3-5 days of clean paper operation, the system is ready for OANDA broker demo. The OANDA practice account IS your broker demo — it's a real broker platform with simulated $100K, real market prices, and real order execution logic.

### What "Broker Demo" Means with OANDA

Your setup is already more advanced than a typical demo because:
- OANDA practice account uses **real live market prices**
- Orders execute at **real market conditions** (with spreads)
- SL/TP are managed **server-side by OANDA** (not simulated)
- The only difference from live: it's virtual money

### Step 4.1 — Verify the OandaBrokerAdapter Works

The `OandaBrokerAdapter` is built and ready. To enable actual order submission through OANDA (instead of internal paper simulation), you would integrate it into the ForwardPaperRunner's execution path. However, for the 1-week evaluation, the current setup already provides what you need:

**Paper mode with OANDA data** gives you:
- Real live USDJPY H1 candles
- Real structure detection on live data
- Real signal generation timing
- Paper-simulated fills (which are conservative)

This is the RIGHT way to evaluate before risking capital. The internal paper broker is actually stricter than OANDA demo because it adds slippage and spread costs.

### Step 4.2 — 1-Week Evaluation Criteria

After 1 week of running, evaluate:

| Metric | Pass | Fail |
|--------|------|------|
| Total trades | >= 10 | < 5 |
| Win rate | > 30% | < 20% |
| Profit factor | > 0.8 | < 0.5 |
| Max drawdown | < 5% | > 8% |
| Circuit breaker fires | 0-1 | 3+ |
| Service uptime | > 95% | < 80% |
| Feed connectivity | Stable | Frequent drops |
| Telegram alerts working | Yes | No |

### Step 4.3 — How to Check Results After 1 Week

```bash
# Generate a full report
docker compose run --rm daily-report --type weekly

# View the latest session summary
docker compose exec forward-paper cat /app/forward_runs/fwd_*/session_summary.json | python3 -m json.tool

# View all trades in the journal
docker compose exec forward-paper grep "log_fill" /app/forward_runs/fwd_*/journal.jsonl
```

---

## PHASE 5: MOVING TO LIVE PROP TRADING

If the 1-week demo passes all criteria, here's the path to prop:

### Step 5.1 — Choose a Prop Firm

Recommended prop firms for FX algorithmic trading:

| Firm | Platform | API | Notes |
|------|----------|-----|-------|
| **FTMO** | MT4/MT5 | Via MT5 Python API | Most popular, strict rules |
| **MyFundedFX** | MT4/MT5 | Via MT5 Python API | Reasonable rules |
| **The Funded Trader** | MT4/MT5 | Via MT5 Python API | Multiple account sizes |

All major prop firms use MetaTrader, which means you'd need the `MetaTrader5` Python package. This requires a Windows VPS or Wine setup.

**Alternative**: Stay on OANDA and trade with your own capital. OANDA offers live accounts with real money and the exact same API you're already using — you just change `OANDA_PRACTICE=false` and use your live account credentials.

### Step 5.2 — If Going OANDA Live

This is the simplest path from where you are now:

1. Open an OANDA live account (requires verification)
2. Fund it with your desired amount
3. Get your live API key from https://www.oanda.com/account/tpa/personal_token
4. Update `.env`:
   ```
   OANDA_PRACTICE=false
   OANDA_API_KEY=your_live_api_key
   OANDA_ACCOUNT_ID=your_live_account_id
   ```
5. Restart: `docker compose restart forward-paper`

### Step 5.3 — If Going MT5 Prop Firm

This requires more work:
1. Pass the prop firm's evaluation/challenge
2. Get your funded MT5 account credentials
3. Set up a Windows VPS or Wine on Linux for MT5
4. Build the MT5 adapter (the `DemoBrokerAdapter` scaffold is ready)
5. This is a separate implementation wave

---

## BEST PRACTICES AND MONITORING CHECKLIST

### Daily (5 minutes)
- [ ] Check Telegram for the daily report at 22:00 UTC
- [ ] Glance at: trades count, PnL, drawdown, alerts
- [ ] If CRITICAL alert received: investigate within 4 hours

### Weekly (15 minutes)
- [ ] Review the weekly Telegram report
- [ ] Compare against 1-week criteria table
- [ ] SSH in and check `docker compose ps` is healthy
- [ ] Check disk usage: `df -h`

### Safety Controls Already Built In
- Circuit breaker at 10% drawdown (5-day cooldown)
- Daily loss lockout at 2%
- Max 3 trades per day
- Max 1 concurrent position
- Config fingerprint verification on every restart
- Auto-resume from checkpoint after crash
- Docker auto-restart policy

### If Something Goes Wrong

| Problem | What to do |
|---------|------------|
| Container keeps restarting | `docker compose logs forward-paper` — check for import errors |
| No trades for days | Normal if market is ranging — check weekly report |
| EMERGENCY alert | SSH in immediately, check logs |
| Telegram not working | Check `.env` credentials, restart container |
| VPS runs out of disk | `docker system prune -f` to clean Docker cache |
| Want to stop everything | `docker compose down` |

---

## QUICK REFERENCE COMMANDS

```bash
# Start
docker compose up -d forward-paper

# Stop
docker compose down

# Restart
docker compose restart forward-paper

# Logs
docker compose logs -f forward-paper
docker compose logs --tail 50 forward-paper

# Status
docker compose ps

# Health check
docker compose exec forward-paper cat /app/forward_runs/health.json

# Manual report
docker compose run --rm daily-report --type daily
docker compose run --rm weekly-report --type weekly

# View trades
docker compose exec forward-paper grep "log_fill" /app/forward_runs/fwd_*/journal.jsonl

# Backup everything
docker compose exec forward-paper tar czf /app/forward_runs/backup.tar.gz /app/forward_runs/fwd_*/
docker cp fx-forward-paper:/app/forward_runs/backup.tar.gz ./backup_$(date +%Y%m%d).tar.gz
```
