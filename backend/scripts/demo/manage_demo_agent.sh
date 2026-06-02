#!/usr/bin/env bash
# Demo Agent Management Script for Railway Production
# This script provides consistent management of the Alyx demo agent on Railway

set -euo pipefail
IFS=$'\n\t'

# This script lives at ``backend/scripts/demo/``; the backend project dir (which
# contains the importable ``scripts`` package) is two directories up.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

print_header() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# Check if Railway CLI is installed
if ! command -v railway &> /dev/null; then
    print_error "Railway CLI not found. Install it with: npm i -g @railway/cli"
    exit 1
fi

# Main menu
show_menu() {
    print_header "Demo Agent Management (Railway Production)"
    echo ""
    echo "1) Update demo agent on Railway (run create_demo_agent.py)"
    echo "2) Check Railway environment variables"
    echo "3) View Railway logs (demo agent activity)"
    echo "4) Open Railway dashboard"
    echo "5) Run create_demo_agent.py locally (for testing)"
    echo "6) Exit"
    echo ""
}

# Update demo agent on Railway
update_on_railway() {
    print_header "Updating Demo Agent on Railway"
    echo ""

    cd "$PROJECT_DIR"

    print_warning "This will run create_demo_agent.py on Railway production..."
    read -p "Continue? (y/N) " -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_success "Running create_demo_agent.py on Railway..."
        railway run python scripts/demo/create_demo_agent.py --env production
        print_success "Demo agent updated!"
    else
        print_warning "Cancelled"
    fi
}

# Check environment variables
check_env_vars() {
    print_header "Railway Environment Variables"
    echo ""

    print_success "Checking DEMO_WORKSPACE_ID and DEMO_AGENT_ID..."
    railway variables | grep -E "(DEMO_WORKSPACE_ID|DEMO_AGENT_ID)" || print_warning "No DEMO variables found"

    echo ""
    read -p "Show all environment variables? (y/N) " -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        railway variables
    fi
}

# View Railway logs
view_logs() {
    print_header "Railway Logs (Press Ctrl+C to exit)"
    echo ""
    railway logs
}

# Open Railway dashboard
open_dashboard() {
    print_success "Opening Railway dashboard..."
    railway open
}

# Run locally for testing
run_locally() {
    print_header "Running create_demo_agent.py Locally"
    echo ""

    cd "$PROJECT_DIR"

    print_warning "This will update the agent in your LOCAL database..."
    read -p "Continue? (y/N) " -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_success "Running locally..."
        uv run python scripts/demo/create_demo_agent.py --env local
    else
        print_warning "Cancelled"
    fi
}

# Main loop
while true; do
    show_menu
    read -r -p "Select an option: " choice
    echo ""

    case $choice in
        1)
            update_on_railway
            ;;
        2)
            check_env_vars
            ;;
        3)
            view_logs
            ;;
        4)
            open_dashboard
            ;;
        5)
            run_locally
            ;;
        6)
            print_success "Goodbye!"
            exit 0
            ;;
        *)
            print_error "Invalid option"
            ;;
    esac

    echo ""
    read -r -p "Press Enter to continue..."
    clear
done
