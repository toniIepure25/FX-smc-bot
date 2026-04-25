# VPS Setup Guide

## 1. Choose a VPS Provider

Recommended for free trial:
- **Oracle Cloud** — always-free tier (1 vCPU, 1 GB RAM, 50 GB disk)
- **Hetzner** — cheapest paid option (~€4/mo)
- **DigitalOcean** — $4/mo droplet
- **Vultr** — $2.50/mo (low-RAM)

Minimum: 1 vCPU, 512 MB RAM, 5 GB disk, Ubuntu 22.04+

## 2. Initial Server Setup

```bash
# SSH into VPS
ssh root@your-vps-ip

# Create a non-root user
adduser fx
usermod -aG sudo fx
su - fx

# Update system
sudo apt update && sudo apt upgrade -y
```

## 3. Install Docker

```bash
sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER
# Log out and back in for group to take effect
exit
ssh fx@your-vps-ip
```

## 4. Deploy the Project

```bash
# Clone or upload the repo
cd /opt
sudo mkdir fx-smc-bot && sudo chown $USER:$USER fx-smc-bot
# Option A: git clone
git clone https://github.com/your-repo/fx-smc-bot.git /opt/fx-smc-bot
# Option B: scp from local machine
# scp -r ./FX-smc-bot fx@your-vps-ip:/opt/fx-smc-bot
```

## 5. Configure

```bash
cd /opt/fx-smc-bot
cp .env.example .env
nano .env  # Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
```

## 6. Upload Historical Data

```bash
mkdir -p data/real
# Upload H1 and H4 data files
# scp data/real/*.parquet fx@your-vps-ip:/opt/fx-smc-bot/data/real/
```

## 7. Build and Start

```bash
docker compose build
docker compose up -d forward-paper
docker compose logs -f forward-paper
```

## 8. Verify

- Check Telegram for startup alert
- Check health: `cat forward_runs/health.json`
- Check logs: `docker compose logs --tail 20 forward-paper`

## 9. Install Cron Jobs

```bash
crontab deploy/crontab
crontab -l  # verify
```

## 10. Set Up Firewall (Optional)

```bash
sudo ufw allow ssh
sudo ufw enable
# No other ports needed — Telegram uses outbound HTTPS
```
