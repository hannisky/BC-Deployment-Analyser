#!/bin/bash
set -euo pipefail

# =============================================================================
# BC Deployment Analyzer — Resource Cleanup
# Deletes the resource group created by setup/deploy.sh (Foundry account/project,
# model deployment, Log Analytics, Application Insights). Local output/ is kept.
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  echo "Loaded environment from: $ENV_FILE"
else
  echo "Warning: .env not found at $ENV_FILE — set RESOURCE_GROUP manually."
fi

RESOURCE_GROUP="${RESOURCE_GROUP:-}"
if [[ -z "$RESOURCE_GROUP" ]]; then
  echo "Error: RESOURCE_GROUP is not set."
  echo "Usage: RESOURCE_GROUP=bc-deployment-analyzer-rg-<suffix> bash cleanup.sh"
  exit 1
fi

echo ""
echo "  This permanently deletes resource group '$RESOURCE_GROUP' and everything in it."
read -r -p "  Type the resource group name to confirm: " CONFIRM
if [[ "$CONFIRM" != "$RESOURCE_GROUP" ]]; then
  echo "Cancelled. No resources were deleted."
  exit 0
fi

az group delete --name "$RESOURCE_GROUP" --yes --no-wait
echo "✅ Deletion initiated (runs in the background)."
echo "   Verify: https://portal.azure.com/#view/HubsExtension/BrowseResourceGroups"
