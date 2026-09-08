#!/bin/bash
# Run this in Claude Code remote session to configure SSH access to your Mac
# Prerequisites: You must run setup-remote-access.sh on your Mac first

set -e

echo "═══════════════════════════════════════"
echo "Setting up remote SSH in this session"
echo "═══════════════════════════════════════"
echo ""

# Get hostname and config info
read -p "Your Mac hostname (from 'hostname' command): " MAC_HOSTNAME
read -p "Your Mac username: " MAC_USERNAME
read -p "Path to private key on your Mac (~/.ssh/claude-hermes): " -e MAC_KEY_PATH

MAC_KEY_PATH="${MAC_KEY_PATH:=$HOME/.ssh/claude-hermes}"

echo ""
echo "Configuration:"
echo "  Hostname: $MAC_HOSTNAME"
echo "  User: $MAC_USERNAME"
echo "  Key: $MAC_KEY_PATH"
echo ""

# Create SSH config
SSH_CONFIG_DIR="$HOME/.ssh"
mkdir -p "$SSH_CONFIG_DIR"

cat >> "$SSH_CONFIG_DIR/config" << EOF

# Claude Code remote → Mac
Host hermes-mac
    HostName $MAC_HOSTNAME
    User $MAC_USERNAME
    IdentityFile $MAC_KEY_PATH
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    ConnectTimeout 10
EOF

chmod 600 "$SSH_CONFIG_DIR/config"

echo "✓ SSH config created"
echo ""
echo "Testing connection..."

if ssh -o ConnectTimeout=5 hermes-mac "echo 'Connected to Mac'" 2>/dev/null; then
    echo "✓ SSH connection successful!"
    echo ""
    echo "You can now run commands on your Mac:"
    echo "  ssh hermes-mac 'python3 scripts/ib-gateway-deploy.py'"
    echo ""
else
    echo "✗ Connection failed. Troubleshoot:"
    echo "  1. Verify Mac hostname: ssh $MAC_HOSTNAME"
    echo "  2. Check SSH is enabled: systemsetup -getremotelogin"
    echo "  3. Verify key path exists: cat $MAC_KEY_PATH"
fi
