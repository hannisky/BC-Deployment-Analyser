#!/bin/bash
set -euo pipefail

# =============================================================================
# BC Deployment Analyzer — Infrastructure Deployment Script
# Provisions a DEDICATED resource group with:
#   Microsoft Foundry account + project + model deployment, Log Analytics, App Insights
# Adapted from the FrontierWeekHack lab deploy.sh. Region default: swedencentral
#
# Usage:  bash setup/deploy.sh [--tags 'Key=Value' ...]
# Env overrides: SUFFIX, RESOURCE_GROUP, LOCATION, MODEL_NAME, MODEL_VERSION, ...
# =============================================================================

az config set extension.use_dynamic_install=yes_without_prompt --only-show-errors >/dev/null 2>&1 || true
az extension add --name application-insights --only-show-errors >/dev/null 2>&1 || true

# --- Configuration -----------------------------------------------------------
SUFFIX="${SUFFIX:-$(openssl rand -hex 3)}"
RESOURCE_GROUP="${RESOURCE_GROUP:-bc-deployment-analyzer-rg-$SUFFIX}"
LOCATION="${LOCATION:-swedencentral}"
FOUNDRY_RESOURCE_NAME="${FOUNDRY_RESOURCE_NAME:-bc-analyzer-$SUFFIX}"
PROJECT_NAME="${PROJECT_NAME:-bc-deployment-analyzer}"
MODEL_DEPLOYMENT_NAME="${MODEL_DEPLOYMENT_NAME:-gpt-5.4}"
MODEL_NAME="${MODEL_NAME:-gpt-5.4}"
MODEL_VERSION="${MODEL_VERSION:-2026-03-05}"
MODEL_CAPACITY="${MODEL_CAPACITY:-30}"
LOG_ANALYTICS_NAME="${LOG_ANALYTICS_NAME:-bc-analyzer-logs-$SUFFIX}"
APP_INSIGHTS_NAME="${APP_INSIGHTS_NAME:-bc-analyzer-insights-$SUFFIX}"

TAGS=("solution=bc-deployment-analyzer" "environment=dev")
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tags)
            shift
            while [[ $# -gt 0 && "$1" != --* ]]; do TAGS+=("$1"); shift; done
            ;;
        *)
            echo "Unknown argument: $1" >&2
            echo "Usage: deploy.sh [--tags 'Key=Value' ...]" >&2
            exit 1
            ;;
    esac
done

echo "=============================================="
echo "  BC Deployment Analyzer — Infrastructure"
echo "=============================================="
echo ""
echo "Resource Group:    $RESOURCE_GROUP"
echo "Location:          $LOCATION"
echo "Foundry Resource:  $FOUNDRY_RESOURCE_NAME"
echo "Project:           $PROJECT_NAME"
echo "Model Deployment:  $MODEL_DEPLOYMENT_NAME ($MODEL_NAME $MODEL_VERSION, ${MODEL_CAPACITY}K TPM)"
echo "Tags:              ${TAGS[*]}"
echo ""

SUBSCRIPTION_ID=$(az account show --query id -o tsv)

# --- Resource Group ----------------------------------------------------------
echo ">>> Creating resource group..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --tags "${TAGS[@]}" --output none

# --- Foundry account (AIServices) -------------------------------------------
echo ">>> Creating Microsoft Foundry account (AIServices)..."
az rest \
    --method PUT \
    --url "https://management.azure.com/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.CognitiveServices/accounts/$FOUNDRY_RESOURCE_NAME?api-version=2026-03-01" \
    --body "{\"kind\": \"AIServices\", \"sku\": {\"name\": \"S0\"}, \"location\": \"$LOCATION\", \"identity\": {\"type\": \"SystemAssigned\"}, \"properties\": {\"customSubDomainName\": \"$FOUNDRY_RESOURCE_NAME\", \"publicNetworkAccess\": \"Enabled\", \"allowProjectManagement\": true}}" \
    --output none || true

echo ">>> Waiting for the account to reach Succeeded state..."
for i in $(seq 1 36); do
    PROV_STATE=$(az cognitiveservices account show --name "$FOUNDRY_RESOURCE_NAME" --resource-group "$RESOURCE_GROUP" \
        --query "properties.provisioningState" -o tsv 2>/dev/null || echo "Pending")
    if [ "$PROV_STATE" = "Succeeded" ]; then echo "    ✓ Provisioning complete."; break
    elif [ "$PROV_STATE" = "Failed" ]; then echo "❌ Foundry account provisioning failed."; exit 1; fi
    echo "    State: $PROV_STATE — retrying in 10s... ($i/36)"
    sleep 10
done

FOUNDRY_RESOURCE_ID=$(az cognitiveservices account show --name "$FOUNDRY_RESOURCE_NAME" --resource-group "$RESOURCE_GROUP" --query id -o tsv)
az resource update --ids "$FOUNDRY_RESOURCE_ID" --set properties.disableLocalAuth=false --output none || true
az resource update --ids "$FOUNDRY_RESOURCE_ID" --set properties.allowProjectManagement=true --output none

DISABLE_LOCAL_AUTH=$(az cognitiveservices account show --name "$FOUNDRY_RESOURCE_NAME" --resource-group "$RESOURCE_GROUP" --query properties.disableLocalAuth -o tsv)
if [ "$DISABLE_LOCAL_AUTH" = "true" ]; then
    echo "⚠️  API key auth is disabled by policy — all scripts use DefaultAzureCredential (Entra ID), so this is fine."
fi

echo ">>> Creating Foundry project..."
az cognitiveservices account project create \
    --name "$FOUNDRY_RESOURCE_NAME" --resource-group "$RESOURCE_GROUP" \
    --project-name "$PROJECT_NAME" --location "$LOCATION" --output none

# --- Model deployment --------------------------------------------------------
echo ">>> Deploying model: $MODEL_NAME ($MODEL_VERSION)..."
az cognitiveservices account deployment create \
    --name "$FOUNDRY_RESOURCE_NAME" --resource-group "$RESOURCE_GROUP" \
    --deployment-name "$MODEL_DEPLOYMENT_NAME" \
    --model-name "$MODEL_NAME" --model-version "$MODEL_VERSION" --model-format OpenAI \
    --sku-capacity "$MODEL_CAPACITY" --sku-name GlobalStandard --output none

# --- Log Analytics + Application Insights ------------------------------------
echo ">>> Creating Log Analytics workspace..."
az monitor log-analytics workspace create --resource-group "$RESOURCE_GROUP" --workspace-name "$LOG_ANALYTICS_NAME" --location "$LOCATION" --output none
LOG_ANALYTICS_ID=$(az monitor log-analytics workspace show --resource-group "$RESOURCE_GROUP" --workspace-name "$LOG_ANALYTICS_NAME" --query id -o tsv)

echo ">>> Creating Application Insights..."
az monitor app-insights component create --app "$APP_INSIGHTS_NAME" --resource-group "$RESOURCE_GROUP" --location "$LOCATION" --workspace "$LOG_ANALYTICS_ID" --output none
APP_INSIGHTS_CONN_STRING=$(az monitor app-insights component show --app "$APP_INSIGHTS_NAME" --resource-group "$RESOURCE_GROUP" --query connectionString -o tsv)
APP_INSIGHTS_INSTRUMENTATION_KEY=$(az monitor app-insights component show --app "$APP_INSIGHTS_NAME" --resource-group "$RESOURCE_GROUP" --query instrumentationKey -o tsv)
APP_INSIGHTS_RESOURCE_ID=$(az monitor app-insights component show --app "$APP_INSIGHTS_NAME" --resource-group "$RESOURCE_GROUP" --query id -o tsv)

echo ">>> Connecting Application Insights to the Foundry account..."
if ! az rest --method PUT \
    --url "https://management.azure.com/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.CognitiveServices/accounts/$FOUNDRY_RESOURCE_NAME/connections/appinsights-conn?api-version=2025-06-01" \
    --body "{\"properties\": {\"category\": \"AppInsights\", \"target\": \"$APP_INSIGHTS_RESOURCE_ID\", \"authType\": \"ApiKey\", \"credentials\": {\"key\": \"$APP_INSIGHTS_CONN_STRING\"}, \"isSharedToAll\": true, \"metadata\": {\"ApiType\": \"Azure\", \"ResourceId\": \"$APP_INSIGHTS_RESOURCE_ID\"}}}" \
    --output none; then
    echo "⚠️  Could not link App Insights automatically — connect it in the Foundry portal under Tracing."
fi

# --- Endpoints ----------------------------------------------------------------
FOUNDRY_ENDPOINT=$(az cognitiveservices account show --name "$FOUNDRY_RESOURCE_NAME" --resource-group "$RESOURCE_GROUP" --query "properties.endpoint" -o tsv)
PROJECT_CONNECTION_STRING=$(az cognitiveservices account project show --name "$FOUNDRY_RESOURCE_NAME" --resource-group "$RESOURCE_GROUP" \
    --project-name "$PROJECT_NAME" --query "properties.endpoints.\"AI Foundry API\"" -o tsv)

# --- Write .env (preserving GitHub/BC secrets from an existing file) ---------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

keep() { # keep VAR — echo existing value from the old .env, if any
    [[ -f "$ENV_FILE" ]] && grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- || true
}
GITHUB_TOKEN_KEEP="$(keep GITHUB_TOKEN)"
BC_CLIENT_ID_KEEP="$(keep BC_CLIENT_ID)"
BC_CLIENT_SECRET_KEEP="$(keep BC_CLIENT_SECRET)"
BC_TENANT_ID_KEEP="$(keep BC_TENANT_ID)"
BC_ENVIRONMENT_KEEP="$(keep BC_ENVIRONMENT)"
BC_COMPANY_NAME_KEEP="$(keep BC_COMPANY_NAME)"
BC_OWN_PUBLISHER_KEEP="$(keep BC_OWN_PUBLISHER)"

echo ">>> Writing .env file to: $ENV_FILE"
cat > "$ENV_FILE" << EOF
# =============================================================================
# BC Deployment Analyzer — Environment Variables
# Auto-generated by setup/deploy.sh on $(date)
# =============================================================================

# Azure / Microsoft Foundry
AZURE_SUBSCRIPTION_ID=$SUBSCRIPTION_ID
RESOURCE_GROUP=$RESOURCE_GROUP
FOUNDRY_RESOURCE_NAME=$FOUNDRY_RESOURCE_NAME
PROJECT_NAME=$PROJECT_NAME
FOUNDRY_ENDPOINT=$FOUNDRY_ENDPOINT
PROJECT_CONNECTION_STRING=$PROJECT_CONNECTION_STRING
MODEL_DEPLOYMENT_NAME=$MODEL_DEPLOYMENT_NAME

# Application Insights & tracing
APPLICATIONINSIGHTS_CONNECTION_STRING=$APP_INSIGHTS_CONN_STRING
APPINSIGHTS_INSTRUMENTATION_KEY=$APP_INSIGHTS_INSTRUMENTATION_KEY
AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true
OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true

# GitHub (fine-grained PAT of the docs bot account — Contents/Metadata/Pull requests: read)
GITHUB_TOKEN=$GITHUB_TOKEN_KEEP

# Business Central (partner-tenant app registration, client credentials via GDAP)
BC_CLIENT_ID=$BC_CLIENT_ID_KEEP
BC_CLIENT_SECRET=$BC_CLIENT_SECRET_KEEP
BC_TENANT_ID=$BC_TENANT_ID_KEEP
BC_ENVIRONMENT=${BC_ENVIRONMENT_KEEP:-Production}
BC_COMPANY_NAME=$BC_COMPANY_NAME_KEEP
BC_OWN_PUBLISHER=$BC_OWN_PUBLISHER_KEEP

# Optional
AZURE_OPENAI_API_KEY=
WORKFLOW_AGENT_NAME=bc-documentation-workflow
EOF

echo ""
echo "=============================================="
echo "  ✅ DEPLOYMENT COMPLETE"
echo "=============================================="
echo ""
echo "  .env written to: $ENV_FILE"
echo "  Next: fill in GITHUB_TOKEN and the BC_* values, then"
echo "        python discovery/discover_repos.py"
echo ""
echo "  Foundry portal: https://ai.azure.com/nextgen  (project: $PROJECT_NAME)"
echo "  Remember: your account needs the 'Azure AI User' / Foundry User role on $FOUNDRY_RESOURCE_NAME"
echo ""
