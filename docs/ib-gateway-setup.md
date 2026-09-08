# IB Gateway Login & AEGIS Trading Setup

Complete guide to setting up IB Gateway authentication for the AEGIS trading agent on your Mac.

## Overview

- **IB Gateway**: Installed on your Mac at `/Applications/IBGateway/IBGateway.app`
- **Hermes**: Remote repository; contains the trading logic
- **Credentials**: Securely encrypted and stored locally on Mac
- **2FA**: Handled via Telegram to your iPhone

## Phase 0 Requirements

✅ IBKR paper account + data pipeline + SQLite logging  
✅ Hard limits: 5% max position, 2% max daily loss, max 5 open positions  
✅ Equities only (no leverage, options, futures, crypto)  
✅ Stop-loss required on every position before entry  
✅ Zero live capital — paper account only until Phase 2 gate approval  

## Setup Instructions

### Step 1: Verify IB Gateway Installation

On your Mac, confirm IB Gateway is installed:

```bash
ls -la /Applications/IBGateway/
# or
ls -la ~/Applications/IBGateway/
```

If not found, download from:
https://www.interactivebrokers.com/en/trading/platforms/ib-gateway.php

### Step 2: Set Up Credential Encryption Key

On your Mac, add the credential encryption key to your shell config:

```bash
# Generate a secure key
export HERMES_CREDENTIAL_KEY="$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")"

# Add to ~/.zshrc (or ~/.bashrc if you use bash)
echo 'export HERMES_CREDENTIAL_KEY="'"$HERMES_CREDENTIAL_KEY"'"' >> ~/.zshrc

# Reload shell
source ~/.zshrc
```

### Step 3: Store Credentials Securely

On your Mac, in the Hermes directory:

```bash
cd /path/to/Hermes
python3 scripts/setup-ib-credentials.py
```

Follow the prompts:
1. Username: `dgwalker2`
2. Password: (your password)
3. Account type: `paper`

Credentials are now encrypted at:
```
~/.hermes/ib_gateway/credentials
```

**Never commit or share this file.**

### Step 4: Set Telegram Environment Variables

On your Mac, add Telegram credentials to `~/.zshrc`:

```bash
export HERMES_TELEGRAM_TOKEN="your_bot_token_from_botfather"
export HERMES_TELEGRAM_CHAT_ID="your_chat_id_from_bot"
```

Get these from:
1. Open Telegram, search `@BotFather`
2. `/newbot` → create "HermesAgent"
3. Save the token
4. Send the bot a message
5. Get chat ID: `curl https://api.telegram.org/bot{TOKEN}/getUpdates`

Reload shell:
```bash
source ~/.zshrc
```

### Step 5: Verify Telegram Connection

Test Telegram:
```bash
python3 scripts/ib-gateway-login.py
# Should prompt for 2FA via Telegram on your iPhone
```

## Daily Login

Run this every morning to authenticate with IB Gateway:

```bash
cd /path/to/Hermes
python3 scripts/ib-gateway-login.py
```

The script will:
1. ✅ Load encrypted credentials
2. 🚀 Launch IB Gateway
3. ⏳ Wait for gateway to be accessible
4. 🔐 Prompt for 2FA code (sent to your iPhone via Telegram)
5. 💾 Save session token (valid 24 hours)

## AEGIS Trading Agent

Once authenticated, AEGIS can:

### Monitor Positions
```python
from agent.aegis_trading import AEGISTrader

trader = AEGISTrader()
trader.ensure_gateway_connected()
print(trader.daily_summary())
```

### Check Constraints
```python
audit = trader.check_constraints()
print(f"Violations: {audit['violations']}")
```

### Log Trades
```python
trader.log_trade(
    symbol="AAPL",
    side="buy",
    quantity=10,
    entry_price=150.25,
    stop_loss=147.00,
    exit_price=152.50,  # if closed
    pnl=225.00  # if closed
)
```

## Credential Security

### What's Encrypted?
- Username
- Password
- Account type (paper/live)

### What's NOT Stored?
- Session tokens (ephemeral, 24-hour validity)
- 2FA codes (never stored)

### Key Derivation
```
HERMES_CREDENTIAL_KEY
    ↓
PBKDF2-HMAC-SHA256 (100,000 iterations)
    ↓
Encryption key + IV
    ↓
AES-256-GCM encryption
```

### Files Generated
```
~/.hermes/ib_gateway/
├── credentials      # Encrypted (600 perms, owner only)
└── session.json     # Current session token (600 perms)

~/.hermes/aegis/
└── trading.db       # SQLite trade logs (600 perms)
```

## Troubleshooting

### "Credentials not found"
```bash
python3 scripts/setup-ib-credentials.py
```

### "IB Gateway not accessible"
1. Ensure IB Gateway is running: `open -a IBGateway`
2. Check it's on localhost:4001: `nc -zv 127.0.0.1 4001`

### "2FA code timeout"
- Check your Telegram app for the code prompt
- The system waits 120 seconds for you to reply

### "Session expired"
```bash
# Re-run login
python3 scripts/ib-gateway-login.py
```

## Phase 2 Checklist

Gate requirement: 3 consecutive months of 30-50% returns + all risk rules adhered

Prepare for Phase 2:
- [ ] 3 months of paper trading history logged
- [ ] Zero constraint violations in audit logs
- [ ] Consistent daily returns 30-50% per month
- [ ] Stop-loss compliance 100% (every trade)
- [ ] Position sizing within limits
- [ ] Write Phase 2 approval document

## Files Reference

| File | Purpose |
|------|---------|
| `agent/ib_gateway_auth.py` | Credential encryption/decryption |
| `agent/aegis_trading.py` | Trading logic, constraints, logging |
| `scripts/ib-gateway-login.py` | Daily login automation |
| `scripts/setup-ib-credentials.py` | One-time credential setup |
| `~/.hermes/ib_gateway/credentials` | Encrypted credentials (never commit) |
| `~/.hermes/aegis/trading.db` | SQLite trade history |

## Next Steps

1. ✅ Complete Step 1-5 above
2. Run daily login: `python3 scripts/ib-gateway-login.py`
3. Monitor trades via AEGIS dashboard (TBD)
4. Track P&L toward Phase 2 gate

---

Questions? Check the system preferences in `HERMES_SOUL.md`.
