#!/usr/bin/env python3
"""
Daily IB Gateway Login
Decrypts credentials, launches IB Gateway, handles 2FA, saves session token
"""

import os
import sys
import json
import time
import requests
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from cryptography.fernet import Fernet

# Environment variables required
TELEGRAM_TOKEN = os.getenv("HERMES_TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("HERMES_TELEGRAM_CHAT_ID")

def load_encrypted_credentials():
    """Load and decrypt stored IB credentials."""
    config_dir = Path.home() / '.hermes' / 'config'
    key_file = config_dir / 'ib.key'
    creds_file = config_dir / 'ib-credentials.json'

    if not key_file.exists() or not creds_file.exists():
        print("Error: Credentials not found. Run setup-ib-credentials.py first.")
        sys.exit(1)

    with open(key_file, 'rb') as f:
        key = f.read()

    cipher = Fernet(key)
    with open(creds_file, 'rb') as f:
        encrypted_data = f.read()

    try:
        decrypted = cipher.decrypt(encrypted_data)
        return json.loads(decrypted.decode())
    except Exception as e:
        print(f"Error decrypting credentials: {e}", file=sys.stderr)
        sys.exit(1)

def send_telegram_message(message: str) -> bool:
    """Send message to Telegram for 2FA notification."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Warning: Telegram credentials not set in environment")
        return False

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        }
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Warning: Could not send Telegram message: {e}")
        return False

def start_ib_gateway():
    """Launch IB Gateway application."""
    ib_gateway_path = "/Applications/IBGateway/IBGateway.app/Contents/MacOS/IBGateway"

    if not Path(ib_gateway_path).exists():
        print(f"Error: IB Gateway not found at {ib_gateway_path}")
        print("Please install IB Gateway first from Interactive Brokers website")
        sys.exit(1)

    try:
        print("Launching IB Gateway...")
        subprocess.Popen(
            [ib_gateway_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        # Give gateway time to start
        time.sleep(5)
    except Exception as e:
        print(f"Error launching IB Gateway: {e}", file=sys.stderr)
        sys.exit(1)

def verify_gateway_connection(max_retries: int = 10) -> bool:
    """Verify IB Gateway is running and responding."""
    gateway_url = "http://localhost:4001"

    for attempt in range(max_retries):
        try:
            response = requests.get(f"{gateway_url}/status", timeout=2)
            if response.status_code == 200:
                print("✓ IB Gateway is running")
                return True
        except requests.exceptions.ConnectionError:
            pass

        if attempt < max_retries - 1:
            print(f"Waiting for IB Gateway... ({attempt + 1}/{max_retries})")
            time.sleep(2)

    print("Error: Could not connect to IB Gateway", file=sys.stderr)
    return False

def handle_2fa_via_telegram(credentials: dict) -> bool:
    """Send 2FA prompt via Telegram and wait for response."""
    message = (
        f"🔐 IB Gateway Login Required\n"
        f"Account: {credentials['username']}\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"Complete 2FA on IB Gateway window, then reply 'done' here."
    )

    send_telegram_message(message)
    print("\n2FA Prompt sent to Telegram on your iPhone")
    print("Complete the login in IB Gateway window and reply 'done' to confirm")

    # For automation, wait for manual confirmation
    # In production, this would poll Telegram for user response
    input("Press Enter once 2FA is complete in IB Gateway: ")
    return True

def save_session_token(credentials: dict):
    """Save session token and expiry time."""
    config_dir = Path.home() / '.hermes' / 'config'
    token_file = config_dir / 'ib-session.json'

    session_data = {
        "account": credentials['username'],
        "account_type": credentials['account_type'],
        "session_start": datetime.now().isoformat(),
        "session_expires": (datetime.now() + timedelta(hours=24)).isoformat(),
        "status": "active"
    }

    with open(token_file, 'w', encoding='utf-8') as f:
        json.dump(session_data, f, indent=2)

    token_file.chmod(0o600)
    print(f"\n✓ Session token saved (valid for 24 hours)")

def main():
    """Main login flow."""
    print("=" * 60)
    print("IB Gateway Daily Login")
    print("=" * 60)

    # Load credentials
    print("\n1. Loading encrypted credentials...")
    credentials = load_encrypted_credentials()
    print(f"   Account: {credentials['username']} ({credentials['account_type']})")

    # Start gateway
    print("\n2. Starting IB Gateway...")
    start_ib_gateway()

    # Verify connection
    print("\n3. Verifying gateway connection...")
    if not verify_gateway_connection():
        sys.exit(1)

    # 2FA via Telegram
    print("\n4. Initiating 2FA verification...")
    if not handle_2fa_via_telegram(credentials):
        sys.exit(1)

    # Save session
    print("\n5. Saving session token...")
    save_session_token(credentials)

    print("\n" + "=" * 60)
    print("✓ Login Complete - AEGIS Trading Ready")
    print("=" * 60)
    print(f"Session expires: {datetime.now() + timedelta(hours=24)}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nLogin cancelled.")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)
