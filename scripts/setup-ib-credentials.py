#!/usr/bin/env python3
"""
IB Gateway credential setup with encryption.
Stores IB credentials securely using cryptography.
Never hardcodes credentials in plaintext.
"""

import os
import json
import getpass
from pathlib import Path
from cryptography.fernet import Fernet

def setup_ib_credentials():
    """Prompt for IB credentials and encrypt them."""

    config_dir = Path.home() / ".hermes"
    config_dir.mkdir(exist_ok=True)

    key_file = config_dir / "ib_key.key"
    creds_file = config_dir / "ib_credentials.enc"

    # Generate encryption key if it doesn't exist
    if not key_file.exists():
        key = Fernet.generate_key()
        key_file.write_bytes(key)
        key_file.chmod(0o600)  # Read/write for owner only
        print(f"✓ Generated encryption key: {key_file}")
    else:
        print(f"✓ Using existing encryption key: {key_file}")
        key = key_file.read_bytes()

    # Prompt for credentials
    print("\n--- IB Gateway Credential Setup ---")
    account = input("IB Account (e.g., dgwalker2): ").strip()
    password = getpass.getpass("IB Password: ")
    account_type = input("Account Type [paper|live]: ").strip().lower()

    if account_type not in ["paper", "live"]:
        print("ERROR: Account type must be 'paper' or 'live'")
        return False

    # Encrypt credentials
    cipher = Fernet(key)
    creds_data = {
        "account": account,
        "password": password,
        "account_type": account_type,
    }
    encrypted = cipher.encrypt(json.dumps(creds_data).encode())
    creds_file.write_bytes(encrypted)
    creds_file.chmod(0o600)

    print(f"\n✓ Credentials encrypted: {creds_file}")
    print(f"  Account: {account}")
    print(f"  Type: {account_type}")
    print("\nCredentials are ready for IB Gateway login.")
    return True

def read_ib_credentials():
    """Read and decrypt IB credentials."""
    config_dir = Path.home() / ".hermes"
    key_file = config_dir / "ib_key.key"
    creds_file = config_dir / "ib_credentials.enc"

    if not key_file.exists() or not creds_file.exists():
        raise FileNotFoundError("Credentials not found. Run setup-ib-credentials.py first.")

    key = key_file.read_bytes()
    cipher = Fernet(key)
    encrypted = creds_file.read_bytes()
    decrypted = cipher.decrypt(encrypted)

    return json.loads(decrypted.decode())

if __name__ == "__main__":
    setup_ib_credentials()
