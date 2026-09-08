#!/bin/bash
# One-time setup for remote SSH access from Claude Code remote session
# Run this ONCE on your Mac, then I can execute commands remotely

set -e

echo "═══════════════════════════════════════"
echo "Setting up remote SSH access"
echo "═══════════════════════════════════════"

# 1. Enable SSH on Mac if not already enabled
echo "✓ Checking SSH..."
if ! sudo systemsetup -getremotelogin | grep -q "on"; then
    echo "  Enabling SSH..."
    sudo systemsetup -setremotelogin on
fi
echo "  SSH is enabled"

# 2. Create SSH directory if needed
mkdir -p ~/.ssh
chmod 700 ~/.ssh

# 3. Generate SSH key for Claude Code remote session (if not exists)
KEY_FILE="$HOME/.ssh/claude-hermes"
if [ ! -f "$KEY_FILE" ]; then
    echo "✓ Generating SSH key pair..."
    ssh-keygen -t ed25519 -f "$KEY_FILE" -N "" -C "claude-hermes-remote"
    chmod 600 "$KEY_FILE"
    chmod 644 "$KEY_FILE.pub"
else
    echo "✓ SSH key already exists at $KEY_FILE"
fi

# 4. Add public key to authorized_keys
echo "✓ Configuring authorized access..."
if ! grep -q "claude-hermes-remote" ~/.ssh/authorized_keys 2>/dev/null; then
    cat "$KEY_FILE.pub" >> ~/.ssh/authorized_keys
fi
chmod 600 ~/.ssh/authorized_keys

# 5. Display connection info
echo ""
echo "═══════════════════════════════════════"
echo "✓ Remote access ready!"
echo "═══════════════════════════════════════"
echo ""
echo "Your Mac hostname:"
hostname
echo ""
echo "SSH private key:"
cat "$KEY_FILE" | head -5
echo "... (full key stored)"
echo ""
echo "Next: Run this command in Claude Code remote session:"
echo "  source scripts/setup-remote-ssh.sh"
echo ""
