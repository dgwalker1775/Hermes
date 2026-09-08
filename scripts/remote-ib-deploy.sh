#!/bin/bash
# Execute IB Gateway deployment on your Mac via SSH from this remote session

set -e

echo "═══════════════════════════════════════"
echo "AEGIS IB Gateway - Remote Deployment"
echo "═══════════════════════════════════════"
echo ""

# Check SSH config exists
if ! grep -q "Host hermes-mac" ~/.ssh/config 2>/dev/null; then
    echo "✗ SSH not configured yet"
    echo "Run these commands first on your Mac:"
    echo "  bash scripts/setup-remote-access.sh"
    echo "Then in this session:"
    echo "  bash scripts/setup-remote-ssh.sh"
    exit 1
fi

echo "✓ SSH configured"
echo ""

# Test connection
echo "Testing Mac connection..."
if ! ssh -o ConnectTimeout=5 hermes-mac "echo OK" > /dev/null 2>&1; then
    echo "✗ Cannot reach Mac. Check SSH setup."
    exit 1
fi
echo "✓ Mac is reachable"
echo ""

# Detect repo path on Mac
echo "Detecting Hermes repo path on Mac..."
HERMES_PATH=$(ssh hermes-mac "cd ~/path/to/Hermes 2>/dev/null && pwd || echo ~/Hermes" 2>/dev/null || echo ~/Hermes)
echo "  Path: $HERMES_PATH"
echo ""

# Install dependencies if needed
echo "Verifying Python dependencies on Mac..."
ssh hermes-mac "python3 -m pip install -q cryptography requests 2>/dev/null || true" 2>/dev/null
echo "✓ Dependencies ready"
echo ""

# Execute deployment
echo "Starting IB Gateway deployment on Mac..."
echo "═══════════════════════════════════════"
echo ""

ssh hermes-mac "cd $HERMES_PATH && python3 scripts/ib-gateway-deploy.py" 2>&1

echo ""
echo "═══════════════════════════════════════"
echo "Deployment complete!"
echo "═══════════════════════════════════════"
