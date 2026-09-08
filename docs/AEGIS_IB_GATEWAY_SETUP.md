# AEGIS - Interactive Brokers Gateway Setup

Complete automated deployment for AEGIS trading sub-agent.

## One Command (Mac Terminal)

```bash
cd ~/path/to/Hermes
python3 scripts/ib-gateway-deploy.py
```

That's it. The script handles:
- ✓ Prerequisites check (IB Gateway, Python, env vars)
- ✓ Credential capture (username/password/account type)
- ✓ Credential encryption (Fernet cipher)
- ✓ IB Gateway launch
- ✓ Gateway readiness verification
- ✓ 2FA via Telegram to your iPhone
- ✓ Session state management

## Prerequisites

### 1. IB Gateway Installed
Download from: https://www.interactivebrokers.com/en/trading/gateway-download.php

Default location: `/Applications/IBGateway/IBGateway.app`

### 2. Python Dependencies

```bash
pip3 install -r scripts/requirements-ib.txt
# Or: pip3 install cryptography requests
```

### 3. Telegram Credentials in ~/.zshrc

```bash
# Add to ~/.zshrc:
export HERMES_TELEGRAM_TOKEN="your_bot_token"
export HERMES_TELEGRAM_CHAT_ID="your_chat_id"

# Reload:
source ~/.zshrc
```

## What Happens When You Run

### Step 1: Prerequisites Check
Script verifies IB Gateway is installed, Python modules available, and Telegram env vars set.

### Step 2: Interactive Credential Input
```
Username (e.g., dgwalker2): 
Password: 
Account type [paper/live] (default: paper): paper
```

### Step 3: Encryption & Storage
Credentials encrypted with Fernet cipher:
- Key: `~/.hermes/config/ib.key` (chmod 0o600)
- Credentials: `~/.hermes/config/ib-credentials.json` (encrypted, chmod 0o600)

### Step 4: IB Gateway Launch
Script starts IB Gateway.app in background.

### Step 5: Gateway Verification
Script pings `http://localhost:4001/status` until it responds.

### Step 6: 2FA via Telegram
Script sends message to your iPhone:
```
🔐 AEGIS IB Gateway Login
Account: dgwalker2
Type: PAPER
Time: 14:32:45

1. Complete login in IB Gateway window
2. Reply 'done' when logged in
3. Check password manager if 2FA required
```

Complete the login in the IB Gateway window (includes 2FA if required).

### Step 7: Session Saved
Script records session state:
- `~/.hermes/config/ib-session.json`
- Session valid for 24 hours
- Contains account type and gateway status

## Daily Login

After initial setup, daily login is simpler:

```bash
python3 scripts/ib-gateway-login.py
```

This:
- Loads encrypted credentials
- Launches gateway
- Sends Telegram 2FA reminder
- Saves new 24h session token

## Account Type

**Paper (Recommended for Phase 0):**
- Use for testing, no real capital at risk
- Default selection
- Perfect for AEGIS development

**Live:**
- Requires confirmation
- Real capital deployed
- Gated until Phase 2 completion

## Troubleshooting

### "IB Gateway not found"
Download and install from Interactive Brokers website.

### "cryptography not installed"
```bash
pip3 install cryptography
```

### "Telegram env vars not set"
Add to `~/.zshrc` and run `source ~/.zshrc`:
```bash
export HERMES_TELEGRAM_TOKEN="your_token"
export HERMES_TELEGRAM_CHAT_ID="your_chat_id"
```

### "Gateway not responding"
1. Check IB Gateway window is visible
2. Verify localhost:4001 is accessible
3. Restart IB Gateway and retry

### Credentials Lost/Corrupted
Delete `~/.hermes/config/ib-credentials.json` and run setup again.

## Security Notes

- Credentials never logged to stdout
- Encryption key stored separately from credentials
- Session tokens have 24h expiry
- Password never stored in plaintext
- All config files chmod 0o600 (owner read/write only)

## Integration with AEGIS

Once logged in, AEGIS can:
- Load session token from `~/.hermes/config/ib-session.json`
- Query account balances, positions, orders
- Execute trades (within Phase 0 risk limits)
- Log all activity to SQLite audit trail

See `AEGIS.md` for full trading rules and position limits.
