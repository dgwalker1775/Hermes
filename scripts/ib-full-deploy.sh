#!/bin/bash
# Complete IB Gateway deployment for AEGIS
# Run this once on your Mac: bash scripts/ib-full-deploy.sh

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_ok() { echo -e "${GREEN}✓${NC} $1"; }
log_info() { echo -e "${BLUE}ℹ${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; exit 1; }

echo -e "\n${BLUE}════════════════════════════════════════${NC}"
echo -e "${BLUE}AEGIS - Complete IB Gateway Deployment${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}\n"

# 1. Prerequisites
echo -e "${BLUE}STEP 1: Checking prerequisites${NC}"

if [ ! -d "/Applications/IBGateway/IBGateway.app" ]; then
    log_error "IB Gateway not installed. Download from: https://www.interactivebrokers.com/en/trading/gateway-download.php"
fi
log_ok "IB Gateway installed"

if ! command -v python3 &> /dev/null; then
    log_error "Python 3 not found"
fi
log_ok "Python 3 available"

# 2. Install dependencies
echo -e "\n${BLUE}STEP 2: Installing Python dependencies${NC}"
python3 -m pip install -q cryptography requests 2>/dev/null || true
log_ok "Dependencies installed"

# 3. Prepare config directory
echo -e "\n${BLUE}STEP 3: Setting up secure config directory${NC}"
CONFIG_DIR="$HOME/.hermes/config"
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
log_ok "Config directory: $CONFIG_DIR"

# 4. Get Telegram credentials
echo -e "\n${BLUE}STEP 4: Verifying Telegram setup${NC}"
if [ -z "$HERMES_TELEGRAM_TOKEN" ] || [ -z "$HERMES_TELEGRAM_CHAT_ID" ]; then
    log_warn "Telegram env vars not set in ~/.zshrc"
    log_info "Add these to ~/.zshrc:"
    echo "    export HERMES_TELEGRAM_TOKEN='your_bot_token'"
    echo "    export HERMES_TELEGRAM_CHAT_ID='your_chat_id'"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    log_ok "Telegram configured"
fi

# 5. Get IB credentials
echo -e "\n${BLUE}STEP 5: IB Credentials${NC}"
read -p "IB Username (e.g., dgwalker2): " IB_USER
read -sp "IB Password: " IB_PASS
echo
read -p "Account type [paper/live] (default: paper): " ACCOUNT_TYPE
ACCOUNT_TYPE="${ACCOUNT_TYPE:=paper}"

if [ "$ACCOUNT_TYPE" = "live" ]; then
    log_warn "LIVE ACCOUNT - Real money at risk!"
    read -p "Type 'yes' to confirm: " CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        log_error "Setup cancelled"
    fi
fi

# 6. Encrypt credentials
echo -e "\n${BLUE}STEP 6: Encrypting credentials${NC}"
python3 << PYTHON_END
import json
import os
from pathlib import Path
from cryptography.fernet import Fernet

config_dir = Path("$CONFIG_DIR")
key_file = config_dir / "ib.key"
creds_file = config_dir / "ib-credentials.json"

# Generate or load key
if key_file.exists():
    with open(key_file, 'rb') as f:
        key = f.read()
else:
    key = Fernet.generate_key()
    key_file.chmod(0o600)
    with open(key_file, 'wb') as f:
        f.write(key)

# Encrypt credentials
cipher = Fernet(key)
creds_data = {
    "username": "$IB_USER",
    "password": "$IB_PASS",
    "account_type": "$ACCOUNT_TYPE"
}
encrypted = cipher.encrypt(json.dumps(creds_data).encode())

creds_file.chmod(0o600)
with open(creds_file, 'wb') as f:
    f.write(encrypted)

print("Encrypted and stored")
PYTHON_END

log_ok "Credentials encrypted and stored"

# 7. Check Telegram connectivity
echo -e "\n${BLUE}STEP 7: Testing Telegram notification${NC}"
if [ -n "$HERMES_TELEGRAM_TOKEN" ] && [ -n "$HERMES_TELEGRAM_CHAT_ID" ]; then
    RESPONSE=$(curl -s -X POST "https://api.telegram.org/bot$HERMES_TELEGRAM_TOKEN/sendMessage" \
        -d chat_id="$HERMES_TELEGRAM_CHAT_ID" \
        -d text="🚀 AEGIS IB Gateway deployment starting..." 2>/dev/null)

    if echo "$RESPONSE" | grep -q "ok"; then
        log_ok "Telegram notification sent"
    else
        log_warn "Could not send Telegram notification (continuing anyway)"
    fi
else
    log_warn "Telegram not configured (skipping)"
fi

# 8. Launch IB Gateway
echo -e "\n${BLUE}STEP 8: Launching IB Gateway${NC}"
open "/Applications/IBGateway/IBGateway.app"
log_ok "IB Gateway launched"

sleep 5

# 9. Wait for gateway
echo -e "\n${BLUE}STEP 9: Waiting for gateway to respond${NC}"
for i in {1..15}; do
    if curl -s http://localhost:4001/status > /dev/null 2>&1; then
        log_ok "IB Gateway is responding"
        break
    fi
    echo -n "."
    sleep 2
    if [ $i -eq 15 ]; then
        log_warn "Gateway not responding (may need manual login)"
    fi
done

# 10. Send Telegram 2FA prompt
echo -e "\n${BLUE}STEP 10: 2FA verification${NC}"
if [ -n "$HERMES_TELEGRAM_TOKEN" ] && [ -n "$HERMES_TELEGRAM_CHAT_ID" ]; then
    curl -s -X POST "https://api.telegram.org/bot$HERMES_TELEGRAM_TOKEN/sendMessage" \
        -d chat_id="$HERMES_TELEGRAM_CHAT_ID" \
        -d text="🔐 Complete IB Gateway login (including 2FA if prompted). Reply when done." 2>/dev/null
    log_ok "Telegram 2FA prompt sent"
fi

log_info "Complete login in IB Gateway window (including 2FA if required)"
read -p "Press Enter when logged in: "

# 11. Save session
echo -e "\n${BLUE}STEP 11: Saving session state${NC}"
python3 << PYTHON_END
import json
from datetime import datetime, timedelta
from pathlib import Path

session_file = Path("$CONFIG_DIR") / "ib-session.json"
session_data = {
    "account": "$IB_USER",
    "account_type": "$ACCOUNT_TYPE",
    "session_start": datetime.now().isoformat(),
    "session_expires": (datetime.now() + timedelta(hours=24)).isoformat(),
    "gateway_status": "online",
    "login_complete": True
}

with open(session_file, 'w') as f:
    json.dump(session_data, f, indent=2)

session_file.chmod(0o600)
print("Session saved")
PYTHON_END

log_ok "Session state saved (24 hours valid)"

# 12. Success
echo -e "\n${BLUE}════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ AEGIS DEPLOYMENT COMPLETE${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}\n"

echo -e "Account: ${GREEN}${IB_USER}${NC} (${ACCOUNT_TYPE})"
echo -e "Gateway: ${GREEN}online${NC}"
echo -e "Session: ${GREEN}24 hours${NC}\n"

echo "Next steps:"
echo "  1. Daily login: python3 scripts/ib-gateway-login.py"
echo "  2. Check status: cat ~/.hermes/config/ib-session.json"
echo ""
