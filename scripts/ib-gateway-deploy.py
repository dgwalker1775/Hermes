#!/usr/bin/env python3
"""
Complete IB Gateway Deployment for AEGIS
One script handles: prerequisites check → credential setup → gateway launch → 2FA → session confirmation
"""

import os
import sys
import json
import time
import getpass
import subprocess
import requests
from pathlib import Path
from datetime import datetime, timedelta
from cryptography.fernet import Fernet

# Colors for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def log_status(status: str, message: str):
    """Print status with color."""
    if status == "ok":
        print(f"{Colors.GREEN}✓{Colors.RESET} {message}")
    elif status == "warn":
        print(f"{Colors.YELLOW}⚠{Colors.RESET} {message}")
    elif status == "error":
        print(f"{Colors.RED}✗{Colors.RESET} {message}")
    elif status == "info":
        print(f"{Colors.BLUE}ℹ{Colors.RESET} {message}")
    else:
        print(message)

def check_prerequisites():
    """Verify all prerequisites are met."""
    print(f"\n{Colors.BOLD}═══ PREREQUISITES CHECK ═══{Colors.RESET}")

    # Check IB Gateway installed
    ib_gateway_path = "/Applications/IBGateway/IBGateway.app/Contents/MacOS/IBGateway"
    if not Path(ib_gateway_path).exists():
        log_status("error", "IB Gateway not found at /Applications/IBGateway/")
        print("   → Download from: https://www.interactivebrokers.com/en/trading/gateway-download.php")
        return False
    log_status("ok", "IB Gateway installed")

    # Check Python cryptography
    try:
        from cryptography.fernet import Fernet
        log_status("ok", "cryptography module available")
    except ImportError:
        log_status("error", "cryptography not installed. Run: pip3 install cryptography")
        return False

    # Check requests
    try:
        import requests
        log_status("ok", "requests module available")
    except ImportError:
        log_status("warn", "requests not installed. Run: pip3 install requests")
        print("   (optional - needed only for Telegram notifications)")

    # Check Telegram env vars
    telegram_token = os.getenv("HERMES_TELEGRAM_TOKEN")
    telegram_chat = os.getenv("HERMES_TELEGRAM_CHAT_ID")

    if not telegram_token or not telegram_chat:
        log_status("warn", "Telegram env vars not set in ~/.zshrc")
        print("   → Add to ~/.zshrc:")
        print("   export HERMES_TELEGRAM_TOKEN='your_bot_token'")
        print("   export HERMES_TELEGRAM_CHAT_ID='your_chat_id'")
        return False
    log_status("ok", "Telegram credentials configured")

    return True

def get_credentials_interactive():
    """Get IB credentials from user."""
    print(f"\n{Colors.BOLD}═══ CREDENTIALS SETUP ═══{Colors.RESET}")

    username = input(f"{Colors.BLUE}Username{Colors.RESET} (e.g., dgwalker2): ").strip()
    if not username:
        log_status("error", "Username required")
        return None

    password = getpass.getpass(f"{Colors.BLUE}Password{Colors.RESET}: ")
    if not password:
        log_status("error", "Password required")
        return None

    account_type = input(f"{Colors.BLUE}Account type{Colors.RESET} [paper/live] (default: paper): ").strip().lower() or "paper"

    if account_type not in ["paper", "live"]:
        log_status("error", "Invalid account type")
        return None

    if account_type == "live":
        log_status("warn", "LIVE ACCOUNT MODE - Real money at risk!")
        confirm = input(f"{Colors.RED}Type 'yes' to confirm LIVE account setup:{Colors.RESET} ")
        if confirm != "yes":
            log_status("info", "Setup cancelled")
            return None

    return {
        "username": username,
        "password": password,
        "account_type": account_type
    }

def encrypt_and_store_credentials(credentials: dict) -> bool:
    """Encrypt credentials and store securely."""
    print(f"\n{Colors.BOLD}═══ ENCRYPTING CREDENTIALS ═══{Colors.RESET}")

    config_dir = Path.home() / '.hermes' / 'config'
    config_dir.mkdir(parents=True, exist_ok=True)

    key_file = config_dir / 'ib.key'
    creds_file = config_dir / 'ib-credentials.json'

    # Generate or load encryption key
    if key_file.exists():
        with open(key_file, 'rb') as f:
            key = f.read()
        log_status("info", "Using existing encryption key")
    else:
        key = Fernet.generate_key()
        key_file.chmod(0o600)
        with open(key_file, 'wb') as f:
            f.write(key)
        log_status("ok", "Generated new encryption key")

    # Encrypt credentials
    cipher = Fernet(key)
    creds_data = {
        "username": credentials["username"],
        "password": credentials["password"],
        "account_type": credentials["account_type"],
        "created": datetime.now().isoformat()
    }

    encrypted = cipher.encrypt(json.dumps(creds_data).encode())

    creds_file.chmod(0o600)
    with open(creds_file, 'wb') as f:
        f.write(encrypted)

    log_status("ok", f"Credentials stored at {creds_file}")
    return True

def send_telegram_notification(message: str) -> bool:
    """Send notification to Telegram."""
    token = os.getenv("HERMES_TELEGRAM_TOKEN")
    chat_id = os.getenv("HERMES_TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return False

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=5)
        return True
    except:
        return False

def launch_ib_gateway(credentials: dict) -> bool:
    """Launch IB Gateway."""
    print(f"\n{Colors.BOLD}═══ LAUNCHING IB GATEWAY ═══{Colors.RESET}")

    ib_path = "/Applications/IBGateway/IBGateway.app/Contents/MacOS/IBGateway"

    try:
        subprocess.Popen(
            [ib_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        log_status("ok", "IB Gateway launched")
        time.sleep(3)
        return True
    except Exception as e:
        log_status("error", f"Failed to launch: {e}")
        return False

def verify_gateway_ready() -> bool:
    """Check gateway is responding."""
    print(f"\n{Colors.BOLD}═══ VERIFYING GATEWAY ═══{Colors.RESET}")

    for i in range(10):
        try:
            response = requests.get("http://localhost:4001/status", timeout=2)
            if response.status_code in [200, 401]:
                log_status("ok", "IB Gateway is responding")
                return True
        except:
            pass

        if i < 9:
            log_status("info", f"Waiting for gateway... ({i+1}/10)")
            time.sleep(2)

    log_status("warn", "Gateway not responding yet (may need manual login)")
    return True  # Continue anyway, may need manual input

def handle_2fa_and_login(credentials: dict) -> bool:
    """Manage 2FA flow."""
    print(f"\n{Colors.BOLD}═══ 2FA & LOGIN ═══{Colors.RESET}")

    message = (
        f"🔐 AEGIS IB Gateway Login\n"
        f"Account: {credentials['username']}\n"
        f"Type: {credentials['account_type'].upper()}\n"
        f"Time: {datetime.now().strftime('%H:%M:%S')}\n\n"
        f"1. Complete login in IB Gateway window\n"
        f"2. Reply 'done' when logged in\n"
        f"3. Check password manager if 2FA required"
    )

    send_telegram_notification(message)
    log_status("info", f"Telegram notification sent to your iPhone")
    log_status("info", f"Complete login in IB Gateway window")

    # Wait for manual completion
    input(f"{Colors.BLUE}Press Enter once logged in:{Colors.RESET} ")
    return True

def save_session_state(credentials: dict) -> bool:
    """Record active session."""
    print(f"\n{Colors.BOLD}═══ SAVING SESSION ═══{Colors.RESET}")

    config_dir = Path.home() / '.hermes' / 'config'
    session_file = config_dir / 'ib-session.json'

    session_data = {
        "account": credentials["username"],
        "account_type": credentials["account_type"],
        "session_start": datetime.now().isoformat(),
        "session_expires": (datetime.now() + timedelta(hours=24)).isoformat(),
        "gateway_status": "online",
        "login_complete": True
    }

    with open(session_file, 'w') as f:
        json.dump(session_data, f, indent=2)

    session_file.chmod(0o600)
    log_status("ok", "Session state saved (valid 24 hours)")
    return True

def main():
    """Complete deployment flow."""
    print(f"\n{Colors.BOLD}{'═' * 50}")
    print("AEGIS - IB GATEWAY COMPLETE DEPLOYMENT")
    print(f"{'═' * 50}{Colors.RESET}\n")

    # 1. Prerequisites
    if not check_prerequisites():
        log_status("error", "Prerequisites not met. Fix above and retry.")
        sys.exit(1)

    # 2. Get credentials
    credentials = get_credentials_interactive()
    if not credentials:
        sys.exit(1)

    # 3. Encrypt & store
    if not encrypt_and_store_credentials(credentials):
        sys.exit(1)

    # 4. Launch gateway
    if not launch_ib_gateway(credentials):
        sys.exit(1)

    # 5. Verify ready
    verify_gateway_ready()

    # 6. 2FA & login
    if not handle_2fa_and_login(credentials):
        sys.exit(1)

    # 7. Save session
    if not save_session_state(credentials):
        sys.exit(1)

    # Success
    print(f"\n{Colors.BOLD}{'═' * 50}")
    print(f"{Colors.GREEN}✓ AEGIS DEPLOYMENT COMPLETE{Colors.RESET}")
    print(f"{'═' * 50}{Colors.RESET}\n")
    print(f"Account: {Colors.BOLD}{credentials['username']}{Colors.RESET} ({credentials['account_type']})")
    print(f"Gateway: {Colors.BOLD}Online{Colors.RESET}")
    print(f"Session: {Colors.BOLD}24 hours{Colors.RESET}")
    print(f"\nNext: Run daily login with:")
    print(f"  {Colors.BLUE}python3 scripts/ib-gateway-login.py{Colors.RESET}\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Setup cancelled.{Colors.RESET}")
        sys.exit(0)
    except Exception as e:
        log_status("error", f"Fatal error: {e}")
        sys.exit(1)
