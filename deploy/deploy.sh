#!/usr/bin/env bash
# Deploy PG Connector to Azure Container Apps (same VNet as PostgreSQL).
# See deploy.ps1 for the annotated version. Secrets come from the environment:
#   export PGPASSWORD=...          (required)
#   export LLM_API_KEY=...         (only if LLM_ENABLED=true)
# Usage:  ./deploy/deploy.sh
set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────────────
RG="Zenlabs-Agent-Foundry"
ENVNAME="zaf-aca-pvt-env"
ACR="<your-acr-name>"                # name only, no .azurecr.io
APP="pg-connector"
TAG="latest"
PORT=8000

PGHOST="zaf-phoenix-postgres.postgres.database.azure.com"
PGUSER="zafadmin"
PGDATABASE="postgres"
PGSSLMODE="require"

LLM_ENABLED="false"
LLM_PROVIDER="azure_openai"
LLM_MODEL="gpt-4o-mini"
# Azure OpenAI (used when LLM_PROVIDER=azure_openai)
AZURE_OPENAI_ENDPOINT="https://<your-resource>.openai.azure.com"
AZURE_OPENAI_DEPLOYMENT="gpt-4o-mini"
AZURE_OPENAI_API_VERSION="2024-06-01"

# ── Guards ──────────────────────────────────────────────────────────────────
: "${PGPASSWORD:?Set PGPASSWORD before running (DB password)}"
if [ "$LLM_ENABLED" = "true" ]; then : "${LLM_API_KEY:?LLM_ENABLED=true but LLM_API_KEY not set}"; fi
IMAGE="$ACR.azurecr.io/$APP:$TAG"

# ── 1. Build in ACR ─────────────────────────────────────────────────────────
echo "==> Building $IMAGE in ACR '$ACR'..."
az acr build --registry "$ACR" --image "$APP:$TAG" --file Dockerfile .

az acr update -n "$ACR" --admin-enabled true >/dev/null
ACR_USER=$(az acr credential show -n "$ACR" --query username -o tsv)
ACR_PASS=$(az acr credential show -n "$ACR" --query "passwords[0].value" -o tsv)

# ── 2. Secrets + env vars ───────────────────────────────────────────────────
# DEPLOY_MODE=vnet: container + DB share the VNet (no VPN in the path), so the
#   connection-status card reports the honest 'in-vnet' state.
# MAX_ROWS=10000: match the intended cap (config.py default is 1000).
SECRETS=(pgpassword="$PGPASSWORD")
ENVVARS=(PGHOST="$PGHOST" PGUSER="$PGUSER" PGDATABASE="$PGDATABASE" PGSSLMODE="$PGSSLMODE" PGPASSWORD=secretref:pgpassword DEPLOY_MODE=vnet MAX_ROWS=10000)
if [ "$LLM_ENABLED" = "true" ]; then
  SECRETS+=(llmkey="$LLM_API_KEY")
  ENVVARS+=(LLM_ENABLED=true LLM_PROVIDER="$LLM_PROVIDER" LLM_MODEL="$LLM_MODEL" LLM_API_KEY=secretref:llmkey)
  if [ "$LLM_PROVIDER" = "azure_openai" ]; then
    ENVVARS+=(AZURE_OPENAI_ENDPOINT="$AZURE_OPENAI_ENDPOINT" AZURE_OPENAI_DEPLOYMENT="$AZURE_OPENAI_DEPLOYMENT" AZURE_OPENAI_API_VERSION="$AZURE_OPENAI_API_VERSION")
  fi
fi

# ── 3. Create or update ─────────────────────────────────────────────────────
if az containerapp show -n "$APP" -g "$RG" --query name -o tsv >/dev/null 2>&1; then
  echo "==> Updating existing Container App '$APP'..."
  az containerapp secret set -n "$APP" -g "$RG" --secrets "${SECRETS[@]}" >/dev/null
  az containerapp update -n "$APP" -g "$RG" --image "$IMAGE" --set-env-vars "${ENVVARS[@]}" >/dev/null
else
  echo "==> Creating Container App '$APP' in '$ENVNAME'..."
  az containerapp create \
    --name "$APP" --resource-group "$RG" --environment "$ENVNAME" \
    --image "$IMAGE" --target-port "$PORT" --ingress external \
    --registry-server "$ACR.azurecr.io" --registry-username "$ACR_USER" --registry-password "$ACR_PASS" \
    --secrets "${SECRETS[@]}" --env-vars "${ENVVARS[@]}" \
    --min-replicas 1 --max-replicas 2 >/dev/null
fi

FQDN=$(az containerapp show -n "$APP" -g "$RG" --query "properties.configuration.ingress.fqdn" -o tsv)
echo ""
echo "==> Deployed. URL: https://$FQDN"
