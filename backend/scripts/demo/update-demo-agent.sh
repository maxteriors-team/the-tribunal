#!/usr/bin/env bash
# Quick update script for demo agent on Railway production
# Usage: ./update-demo-agent.sh

set -euo pipefail
IFS=$'\n\t'

# This script lives at ``backend/scripts/demo/``; the backend project dir (which
# contains the importable ``scripts`` package) is two directories up.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "🚀 Updating Alyx demo agent on Railway production (--env production)..."
echo ""

cd "$PROJECT_DIR"

# Check if a service is linked
if ! railway status 2>&1 | grep -q "Service:"; then
    echo "⚠️  No Railway service linked. Linking now..."
    echo ""
    echo "Available services:"
    railway service list 2>/dev/null || echo "  Run 'railway service' to link a service"
    echo ""
    echo "💡 Tip: Run 'railway service' and select your backend service"
    exit 1
fi

# Run the create_demo_agent script on Railway. The script's own --env production
# guard prompts for typed confirmation before it writes.
railway run python scripts/demo/create_demo_agent.py --env production

echo ""
echo "✅ Demo agent updated successfully!"
echo ""
echo "To view logs:    railway logs"
echo "To open Railway: railway open"
