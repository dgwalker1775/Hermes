"""Interactive Brokers Gateway authentication and credential management.

Handles secure credential storage, login flow with 2FA, and session persistence
for the AEGIS trading agent's IB Gateway connection.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


@dataclass
class IBCredentials:
    """IB Gateway credentials container (never persisted in plaintext)."""

    username: str
    password: str
    account: str = "paper"  # paper or live

    def __post_init__(self):
        """Validate credentials on creation."""
        if not self.username or not self.password:
            raise ValueError("username and password required")

    def clear(self):
        """Zero out credentials from memory."""
        self.username = ""
        self.password = ""


@dataclass
class IBSessionToken:
    """Encrypted session token for authenticated IB Gateway connection."""

    token_hash: str  # HMAC of actual token for verification
    expires_at: int  # Unix timestamp
    created_at: int
    gateway_host: str = "127.0.0.1"
    gateway_port: int = 4001
    client_id: int = 1  # Hermes AEGIS client ID

    def is_expired(self) -> bool:
        """Check if session token is expired."""
        return time.time() > self.expires_at

    def to_dict(self) -> dict:
        """Serialize to dict for secure storage."""
        return asdict(self)


class IBGatewayAuthManager:
    """Manages IB Gateway authentication and session lifecycle."""

    def __init__(self, credential_store_path: Optional[str] = None):
        """Initialize auth manager.

        Args:
            credential_store_path: Path to encrypted credential store.
                                   Defaults to ~/.hermes/ib_gateway/credentials
        """
        if credential_store_path is None:
            credential_store_path = (
                Path.home() / ".hermes" / "ib_gateway" / "credentials"
            )

        self.credential_store = Path(credential_store_path)
        self.credential_store.parent.mkdir(parents=True, exist_ok=True)
        self.credential_store.parent.chmod(0o700)  # rwx------

        self.session_file = self.credential_store.parent / "session.json"
        self._credentials: Optional[IBCredentials] = None
        self._session_token: Optional[IBSessionToken] = None

    def store_credentials(self, creds: IBCredentials) -> None:
        """Store credentials securely using environment-based encryption.

        Credentials are encrypted with a key derived from HERMES_CREDENTIAL_KEY
        env var. The encrypted blob is stored to disk; plaintext never written.

        Args:
            creds: IBCredentials to encrypt and store
        """
        key = os.environ.get("HERMES_CREDENTIAL_KEY")
        if not key:
            raise ValueError(
                "HERMES_CREDENTIAL_KEY env var not set. "
                "Set it before storing credentials."
            )

        # Create deterministic salt from username
        salt = hashlib.sha256(creds.username.encode()).digest()[:16]

        # Derive encryption key
        derived_key = hashlib.pbkdf2_hmac(
            "sha256", key.encode(), salt, 100000
        )

        # Encrypt using XOR with derived key
        plaintext = json.dumps(
            {
                "username": creds.username,
                "password": creds.password,
                "account": creds.account,
            }
        ).encode()

        # Expand key to match plaintext length
        key_stream = b""
        while len(key_stream) < len(plaintext):
            key_stream += hashlib.sha256(
                derived_key + len(key_stream).to_bytes(8, "big")
            ).digest()

        ciphertext = bytes(
            a ^ b for a, b in zip(plaintext, key_stream[: len(plaintext)])
        )

        # Store with salt and HMAC for verification
        hmac_tag = hmac.new(derived_key, ciphertext, hashlib.sha256).digest()

        encrypted_package = {
            "version": 1,
            "salt": salt.hex(),
            "hmac": hmac_tag.hex(),
            "ciphertext": ciphertext.hex(),
        }

        with open(self.credential_store, "w", encoding="utf-8") as f:
            json.dump(encrypted_package, f)

        os.chmod(self.credential_store, 0o600)  # rw-------

    def load_credentials(self) -> IBCredentials:
        """Load and decrypt stored credentials.

        Returns:
            IBCredentials decrypted from secure storage

        Raises:
            ValueError: If credentials not found or decryption fails
        """
        if not self.credential_store.exists():
            raise ValueError(f"Credentials not found at {self.credential_store}")

        key = os.environ.get("HERMES_CREDENTIAL_KEY")
        if not key:
            raise ValueError("HERMES_CREDENTIAL_KEY env var not set")

        with open(self.credential_store, "r", encoding="utf-8") as f:
            encrypted_package = json.load(f)

        # Decrypt
        salt = bytes.fromhex(encrypted_package["salt"])
        hmac_tag = bytes.fromhex(encrypted_package["hmac"])
        ciphertext = bytes.fromhex(encrypted_package["ciphertext"])

        # Derive same key
        derived_key = hashlib.pbkdf2_hmac(
            "sha256", key.encode(), salt, 100000
        )

        # Verify HMAC
        expected_hmac = hmac.new(derived_key, ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(hmac_tag, expected_hmac):
            raise ValueError("Credential integrity check failed (HMAC mismatch)")

        # Decrypt
        key_stream = b""
        while len(key_stream) < len(ciphertext):
            key_stream += hashlib.sha256(
                derived_key + len(key_stream).to_bytes(8, "big")
            ).digest()

        plaintext = bytes(
            a ^ b for a, b in zip(ciphertext, key_stream[: len(ciphertext)])
        )

        data = json.loads(plaintext.decode())
        return IBCredentials(
            username=data["username"],
            password=data["password"],
            account=data.get("account", "paper"),
        )

    def save_session_token(self, token: IBSessionToken) -> None:
        """Save session token to secure file.

        Args:
            token: Session token to persist
        """
        with open(self.session_file, "w", encoding="utf-8") as f:
            json.dump(token.to_dict(), f)
        os.chmod(self.session_file, 0o600)

    def load_session_token(self) -> Optional[IBSessionToken]:
        """Load session token from file if valid.

        Returns:
            IBSessionToken if valid and not expired, None otherwise
        """
        if not self.session_file.exists():
            return None

        with open(self.session_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        token = IBSessionToken(**data)

        if token.is_expired():
            self.session_file.unlink()
            return None

        return token

    def is_gateway_accessible(
        self,
        host: str = "127.0.0.1",
        port: int = 4001,
        timeout: float = 2.0,
    ) -> bool:
        """Check if IB Gateway is running and accessible.

        Args:
            host: Gateway host (default localhost)
            port: Gateway port (default 4001)
            timeout: Connection timeout in seconds

        Returns:
            True if gateway is accessible, False otherwise
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception:
            return False

    def clear_stored_credentials(self) -> None:
        """Securely delete stored credentials from disk."""
        if self.credential_store.exists():
            # Overwrite with random data before deletion
            with open(self.credential_store, "wb") as f:
                f.write(os.urandom(self.credential_store.stat().st_size))
            self.credential_store.unlink()
