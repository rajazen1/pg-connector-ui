# Deploy PG Connector to Azure Container Apps (same VNet as PostgreSQL).
#
# Builds the image in ACR, then creates/updates the Container App in the
# private environment. The DB password and LLM key are stored as Container App
# SECRETS (never as plaintext env vars).
#
# Prereqs:  az login;  az extension add --name containerapp
# Secrets (do NOT hardcode) — set before running:
#   $env:PGPASSWORD = "..."
#   $env:LLM_API_KEY = "..."   # only if LLM_ENABLED = true
#
# Usage:  ./deploy/deploy.ps1

$ErrorActionPreference = "Stop"

# ── Config ──────────────────────────────────────────────────────────────────
$RG      = "Zenlabs-Agent-Foundry"
$ENVNAME = "zaf-aca-pvt-env"
$ACR     = "<your-acr-name>"                 # e.g. zafacr  (name only, no .azurecr.io)
$APP     = "pg-connector"
$TAG     = "latest"
$PORT    = 8000

# Database (points at the Azure PostgreSQL reachable inside the VNet)
$PGHOST     = "zaf-phoenix-postgres.postgres.database.azure.com"
$PGUSER     = "zafadmin"
$PGDATABASE = "postgres"
$PGSSLMODE  = "require"

# AI (optional). Set $LLM_ENABLED = "true" and export $env:LLM_API_KEY to enable.
$LLM_ENABLED  = "false"
$LLM_PROVIDER = "azure_openai"
$LLM_MODEL    = "gpt-4o-mini"
# Azure OpenAI (used when $LLM_PROVIDER = "azure_openai")
$AZURE_OPENAI_ENDPOINT   = "https://<your-resource>.openai.azure.com"
$AZURE_OPENAI_DEPLOYMENT = "gpt-4o-mini"
$AZURE_OPENAI_API_VERSION = "2024-06-01"

# ── Guard: required secrets ─────────────────────────────────────────────────
if (-not $env:PGPASSWORD) { throw "Set `$env:PGPASSWORD before running (DB password)." }
if ($LLM_ENABLED -eq "true" -and -not $env:LLM_API_KEY) { throw "LLM_ENABLED=true but `$env:LLM_API_KEY is not set." }
$IMAGE = "$ACR.azurecr.io/$APP`:$TAG"

# ── 1. Build image in ACR (no local Docker needed) ──────────────────────────
Write-Host "==> Building $IMAGE in ACR '$ACR'..." -ForegroundColor Cyan
az acr build --registry $ACR --image "$APP`:$TAG" --file Dockerfile .

# ACR pull credentials for the Container App (admin must be enabled)
az acr update -n $ACR --admin-enabled true | Out-Null
$ACR_USER = az acr credential show -n $ACR --query username -o tsv
$ACR_PASS = az acr credential show -n $ACR --query "passwords[0].value" -o tsv

# ── 2. Assemble secrets + env vars ──────────────────────────────────────────
$secrets = @("pgpassword=$($env:PGPASSWORD)")
$envvars = @(
  "PGHOST=$PGHOST", "PGUSER=$PGUSER", "PGDATABASE=$PGDATABASE",
  "PGSSLMODE=$PGSSLMODE", "PGPASSWORD=secretref:pgpassword"
)
if ($LLM_ENABLED -eq "true") {
  $secrets += "llmkey=$($env:LLM_API_KEY)"
  $envvars += @(
    "LLM_ENABLED=true", "LLM_PROVIDER=$LLM_PROVIDER", "LLM_MODEL=$LLM_MODEL",
    "LLM_API_KEY=secretref:llmkey"
  )
  if ($LLM_PROVIDER -eq "azure_openai") {
    $envvars += @(
      "AZURE_OPENAI_ENDPOINT=$AZURE_OPENAI_ENDPOINT",
      "AZURE_OPENAI_DEPLOYMENT=$AZURE_OPENAI_DEPLOYMENT",
      "AZURE_OPENAI_API_VERSION=$AZURE_OPENAI_API_VERSION"
    )
  }
}

# ── 3. Create or update the Container App ───────────────────────────────────
$exists = az containerapp show -n $APP -g $RG --query name -o tsv 2>$null
if ($exists) {
  Write-Host "==> Updating existing Container App '$APP'..." -ForegroundColor Cyan
  az containerapp secret set -n $APP -g $RG --secrets $secrets | Out-Null
  az containerapp update -n $APP -g $RG --image $IMAGE --set-env-vars $envvars | Out-Null
} else {
  Write-Host "==> Creating Container App '$APP' in '$ENVNAME'..." -ForegroundColor Cyan
  az containerapp create `
    --name $APP --resource-group $RG --environment $ENVNAME `
    --image $IMAGE --target-port $PORT --ingress external `
    --registry-server "$ACR.azurecr.io" --registry-username $ACR_USER --registry-password $ACR_PASS `
    --secrets $secrets --env-vars $envvars `
    --min-replicas 1 --max-replicas 2 | Out-Null
}

$fqdn = az containerapp show -n $APP -g $RG --query "properties.configuration.ingress.fqdn" -o tsv
Write-Host "`n==> Deployed. URL: https://$fqdn" -ForegroundColor Green
