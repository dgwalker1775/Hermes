#!/usr/bin/env python3
"""
IB Gateway Credentials Setup
Securely stores encrypted IBKR credentials for AEGIS trading sub-agent
"""

import os
import sys
import json
import getpass
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2

def get_or_create_key(key_file: Path) -> bytes:
    """Get encryption key or create one if it doesn't exist."""
    if key_file.exists():
        with open(key_file, 'rb') as f:
            return f.read()

    # Generate new key from a derived master key
    key = Fernet.generate_key()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.chmod(0o600)
    with open(key_file, 'wb') as f:
        f.write(key)
    return key

def setup_credentials():
    """Interactive setup for IB credentials."""
    config_dir = Path.home() / '.hermes' / 'config'
    config_dir.mkdir(parents=True, exist_ok=True)

    key_file = config_dir / 'ib.key'
    creds_file = config_dir / 'ib-credentials.json'

    print("=" * 60)
    print("IB Gateway Credentials Setup")
    print("=" * 60)

    # Get credentials
    print("\nEnter your Interactive Brokers credentials:")
    username = input("Username (e.g., dgwalker2): ").strip()
    if not username:
        print("Error: Username required")
        sys.exit(1)

    password = getpass.getpass("Password: ")
    if not password:
        print("Error: Password required")
        sys.exit(1)

    account_type = input("Account type [paper/live] (default: paper): ").strip().lower() or "paper"
    if account_type not in ["paper", "live"]:
        print("Error: Account type must be 'paper' or 'live'")
        sys.exit(1)

    # Confirm live account warning
    if account_type == "live":
        confirm = input("\n⚠️  WARNING: Live account selected. Type 'confirm' to proceed: ")
        if confirm != "confirm":
            print("Cancelled.")
            sys.exit(0)

    # Encrypt and store
    key = get_or_create_key(key_file)
    cipher = Fernet(key)

    credentials = {
        "username": username,
        "password": password,
        "account_type": account_type,
        "setup_timestamp": str(Path(creds_file).stat().st_mtime) if creds_file.exists() else "new"
    }

    encrypted_data = cipher.encrypt(json.dumps(credentials).encode())

    creds_file.chmod(0o600)
    with open(creds_file, 'wb') as f:
        f.write(encrypted_data)

    print(f"\n✓ Credentials saved to {creds_file}")
    print(f"✓ Encryption key stored at {key_file}")
    print(f"✓ Account type: {account_type}")
    print(f"\nNext step: Run 'python3 scripts/ib-gateway-login.py' to start IB Gateway")

if __name__ == "__main__":
    try:
        setup_credentials()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
