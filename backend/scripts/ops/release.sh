#!/usr/bin/env bash
# Release script run by Railway as a preDeployCommand.
#
# Runs database migrations before the new container is promoted to serve
# traffic. A non-zero exit aborts the deploy and leaves the previous
# (healthy) revision running, so a bad migration cannot restart-loop the app.

set -euo pipefail

echo "[release] Running alembic upgrade head..."
alembic upgrade head
echo "[release] Migrations applied successfully."
