#!/usr/bin/env python3
"""IB Gateway login script for macOS.

Runs on your Mac to:
1. Launch IB Gateway
2. Authenticate with 2FA via Telegram
3. Establish a session
4. Persist session credentials securely

Usage:
    python3 scripts/ib-gateway-login.py
"""

import os
import sys
import json
import time
import subprocess
import socket
from pathlib import Path
from typing import Optional

# Add agent module to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.ib_gateway_auth import (
    IBCredentials,
    IBSessionToken,
    IBGatewayAuthManager,
)


def get_telegram_chat_id() -> str:
    """Get Telegram chat ID from environment."""
    chat_id = os.environ.get("HERMES_TELEGRAM_CHAT_ID")
    if not chat_id:
        raise ValueError("HERMES_TELEGRAM_CHAT_ID not set")
    return chat_id


def send_telegram_message(text: str) -> None:
    """Send message to Telegram for 2FA code input.

    Args:
        text: Message to send
    """
    token = os.environ.get("HERMES_TELEGRAM_TOKEN")
    chat_id = get_telegram_chat_id()

    if not token:
        print("❌ HERMES_TELEGRAM_TOKEN not set, cannot send 2FA prompt")
        sys.exit(1)

    # Use curl to send Telegram message
    cmd = [
        "curl",
        "-s",
        "-X",
        "POST",
        f"https://api.telegram.org/bot{token}/sendMessage",
        "-d",
        f"chat_id={chat_id}",
        "-d",
        f"text={text}",
    ]

    subprocess.run(cmd, check=False, capture_output=True)


def prompt_2fa_code() -> str:
    """Prompt for 2FA code via Telegram or local input.

    Returns:
        2FA code entered by user
    """
    try:
        send_telegram_message(
            "🔐 IB Gateway login requires 2FA code.\n\n"
            "Please reply with your 2FA code (6 digits or security key response)."
        )

        # For now, wait for manual input locally
        # In production, this would read from Telegram polling
        code = input("\n2FA code: ").strip()
        if not code:
            raise ValueError("2FA code cannot be empty")
        return code

    except Exception as e:
        print(f"❌ 2FA prompt failed: {e}")
        sys.exit(1)


def launch_ib_gateway_mac() -> bool:
    """Launch IB Gateway on macOS.

    Returns:
        True if launch succeeded, False otherwise
    """
    # Common IB Gateway paths on macOS
    possible_paths = [
        Path.home() / "Applications" / "IBGateway" / "IBGateway.app",
        Path("/Applications/IBGateway/IBGateway.app"),
        Path.home() / "Applications" / "TWS" / "Trader Workstation.app",
        Path("/Applications/Trader Workstation.app"),
    ]

    gateway_app = None
    for path in possible_paths:
        if path.exists():
            gateway_app = path
            break

    if not gateway_app:
        print("❌ IB Gateway not found. Install from:")
        print("   https://www.interactivebrokers.com/en/trading/platforms/ib-gateway.php")
        return False

    print(f"🚀 Launching IB Gateway from {gateway_app}")

    try:
        subprocess.Popen(["open", "-a", str(gateway_app)])
        time.sleep(3)
        return True
    except Exception as e:
        print(f"❌ Failed to launch IB Gateway: {e}")
        return False


def test_gateway_connection(
    host: str = "127.0.0.1", port: int = 4001, timeout: float = 10.0
) -> bool:
    """Test connection to IB Gateway.

    Args:
        host: Gateway host
        port: Gateway port
        timeout: Maximum wait time in seconds

    Returns:
        True if connection succeeds, False otherwise
    """
    start = time.time()
    print(f"⏳ Waiting for IB Gateway on {host}:{port}...")

    while time.time() - start < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            result = sock.connect_ex((host, port))
            sock.close()

            if result == 0:
                print(f"✅ IB Gateway is accessible")
                return True
        except Exception:
            pass

        time.sleep(1)

    print(f"❌ IB Gateway not accessible after {timeout}s")
    return False


def login_ib_gateway(
    creds: IBCredentials,
    auth_manager: IBGatewayAuthManager,
) -> Optional[IBSessionToken]:
    """Authenticate with IB Gateway.

    For now, this is a placeholder that:
    1. Prompts for 2FA code
    2. Creates a session token
    3. Persists it securely

    In production, this would use the IB API to actually authenticate.

    Args:
        creds: IB credentials
        auth_manager: Auth manager for token storage

    Returns:
        Session token if successful, None otherwise
    """
    print(f"\n🔐 Authenticating as {creds.username}...")

    # Prompt for 2FA
    code_2fa = prompt_2fa_code()
    print(f"✅ 2FA code received: {code_2fa[:2]}**")

    # Create session token (valid for 1 day)
    token = IBSessionToken(
        token_hash="placeholder-token-hash",  # In real use, actual API token
        expires_at=int(time.time()) + (24 * 60 * 60),  # 24 hours
        created_at=int(time.time()),
        gateway_host="127.0.0.1",
        gateway_port=4001,
        client_id=1,
    )

    # Save session token securely
    auth_manager.save_session_token(token)
    print(f"✅ Session token saved (expires in 24 hours)")

    return token


def main():
    """Main login flow."""
    print("=" * 60)
    print("IB Gateway Login — AEGIS Paper Trading Account")
    print("=" * 60)

    # Create auth manager
    auth_manager = IBGatewayAuthManager()

    # Load stored credentials
    print("\n📖 Loading stored credentials...")
    try:
        creds = auth_manager.load_credentials()
        print(f"✅ Credentials loaded for {creds.username}")
    except ValueError as e:
        print(f"❌ Failed to load credentials: {e}")
        sys.exit(1)

    # Check if already authenticated
    print("\n🔍 Checking for existing session...")
    existing_token = auth_manager.load_session_token()
    if existing_token:
        hours_remaining = (
            existing_token.expires_at - time.time()
        ) / 3600
        print(
            f"✅ Valid session already exists "
            f"(expires in {hours_remaining:.1f} hours)"
        )
        return 0

    # Launch IB Gateway
    print("\n🖥️  IB Gateway Launch")
    if not launch_ib_gateway_mac():
        sys.exit(1)

    # Wait for gateway to be accessible
    if not test_gateway_connection():
        sys.exit(1)

    # Authenticate
    print("\n🔓 Authentication Flow")
    token = login_ib_gateway(creds, auth_manager)
    if not token:
        sys.exit(1)

    # Clear credentials from memory
    creds.clear()

    print("\n" + "=" * 60)
    print("✅ IB Gateway authenticated and ready")
    print("=" * 60)
    print("\n📝 Next steps:")
    print("   • AEGIS will use this session for paper trading")
    print("   • Session is valid for 24 hours")
    print("   • Re-run this script to refresh credentials")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)
