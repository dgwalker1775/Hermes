#!/usr/bin/env python3
"""Setup script to securely store IB Gateway credentials.

Run this ONCE to encrypt and store your credentials.
After this, login.py can use them securely.

Usage:
    python3 scripts/setup-ib-credentials.py
"""

import os
import sys
import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.ib_gateway_auth import IBCredentials, IBGatewayAuthManager


def get_or_create_credential_key() -> str:
    """Get or create the HERMES_CREDENTIAL_KEY.

    This key is used to encrypt stored credentials. It should be stored
    in the user's shell config (.zshrc, .bashrc, etc).

    Returns:
        The credential key
    """
    existing_key = os.environ.get("HERMES_CREDENTIAL_KEY")
    if existing_key:
        print(f"✅ Using existing HERMES_CREDENTIAL_KEY from environment")
        return existing_key

    print(
        "🔑 No HERMES_CREDENTIAL_KEY found.\n"
        "   This key will encrypt your stored credentials.\n"
        "   It must be stored in your shell config (~/.zshrc, ~/.bashrc).\n"
    )

    # For macOS with zsh
    shell_config = Path.home() / ".zshrc"
    if not shell_config.exists():
        shell_config = Path.home() / ".bashrc"

    response = (
        input(f"Create new key and add to {shell_config}? (y/n): ")
        .strip()
        .lower()
    )

    if response != "y":
        print("❌ Cannot proceed without credential key")
        sys.exit(1)

    # Generate a secure random key
    import secrets

    new_key = secrets.token_urlsafe(32)

    # Add to shell config
    with open(shell_config, "a", encoding="utf-8") as f:
        f.write(f'\nexport HERMES_CREDENTIAL_KEY="{new_key}"\n')

    print(f"✅ Key added to {shell_config}")
    print(f"   ⚠️  RESTART YOUR TERMINAL or run: source {shell_config}")

    return new_key


def main():
    """Setup flow."""
    print("=" * 60)
    print("IB Gateway — Secure Credential Setup")
    print("=" * 60)

    # Ensure credential key exists
    print("\n1️⃣  Credential Encryption Key")
    cred_key = get_or_create_credential_key()
    os.environ["HERMES_CREDENTIAL_KEY"] = cred_key

    # Get IB credentials from user
    print("\n2️⃣  IB Gateway Credentials")
    print("   (These will be encrypted and never stored in plaintext)")

    username = input("\nUsername: ").strip()
    if not username:
        print("❌ Username required")
        sys.exit(1)

    password = getpass.getpass("Password: ")
    if not password:
        print("❌ Password required")
        sys.exit(1)

    account_type = (
        input("\nAccount type (paper/live) [paper]: ").strip().lower()
    )
    if not account_type:
        account_type = "paper"

    if account_type not in ("paper", "live"):
        print("❌ Invalid account type")
        sys.exit(1)

    # Create credentials object
    creds = IBCredentials(
        username=username, password=password, account=account_type
    )

    # Store encrypted
    print("\n3️⃣  Encrypting and storing credentials...")
    try:
        auth_manager = IBGatewayAuthManager()
        auth_manager.store_credentials(creds)
        print(f"✅ Credentials encrypted and stored")
        print(
            f"   Location: {auth_manager.credential_store}"
        )

        # Verify we can read them back
        loaded_creds = auth_manager.load_credentials()
        if (
            loaded_creds.username == creds.username
            and loaded_creds.password == creds.password
        ):
            print(f"✅ Verification passed — credentials are retrievable")
        else:
            print(f"❌ Verification failed")
            sys.exit(1)

    except Exception as e:
        print(f"❌ Failed to store credentials: {e}")
        sys.exit(1)

    finally:
        # Clear plaintext from memory
        creds.clear()

    print("\n" + "=" * 60)
    print("✅ Setup Complete")
    print("=" * 60)
    print("\n📝 Next steps:")
    print("   1. Restart your terminal or: source ~/.zshrc")
    print("   2. Run: python3 scripts/ib-gateway-login.py")
    print("   3. Follow the 2FA prompts on your iPhone")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
