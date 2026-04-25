# Alert Routing Guide

## Setup

### 1. Create a Telegram Bot

1. Open Telegram, search for `@BotFather`
2. Send `/newbot`, follow prompts to create a bot
3. Copy the bot token (e.g., `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)

### 2. Get Your Chat ID

1. Send any message to your new bot
2. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Find `"chat": {"id": 123456789}` — that's your chat ID

### 3. Configure

Add to `.env`:
```
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=123456789
```

## Alert Sinks

| Sink | Destination | Min Severity | Purpose |
|------|-------------|-------------|---------|
| `LogAlertSink` | stdout / service.log | ALL | Operational logging |
| `FileAlertSink` | alerts.jsonl | ALL | Audit trail |
| `TelegramAlertSink` | Telegram chat | WARNING | Remote monitoring |

## Deduplication

The `AlertRouter` deduplicates alerts by `category:level` with a 300-second cooldown. This prevents spamming Telegram during repeated feed gaps or risk state oscillations.

## Message Format

```
🚨 *CRITICAL* | `risk_state`
State: active -> stopped (circuit_breaker)
_2026-04-20 14:30:00 UTC_
```

Emojis: ℹ️ INFO, ⚠️ WARNING, 🚨 CRITICAL, 🆘 EMERGENCY

## Report Messages

Daily and weekly reports are sent via `TelegramAlertSink.send_report()` which bypasses severity filtering — reports are always delivered.
