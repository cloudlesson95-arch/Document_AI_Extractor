# ==============================================================================
# Azure teardown for Document AI Extractor: deletes what infra/azure/setup.ps1 and
# the deploy workflow created for -AppName, and nothing else.
# ==============================================================================
# Deleting the app's resource group removes every resource in it (the Container
# App and its environment, registry, logs, storage with every file and record, key
# vault, identity) and their role assignments. Two things outside it go separately:
# the deleted key vault, which Azure keeps recoverable for 7 days and is purged here
# so setup.ps1 can create the same name again, and the deploy workflow's app
# registration.
# Safe to re-run: what's already gone is skipped.
param(
    [string]$AppName = "docai",
    [string]$ResourceGroup = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$names = Get-ResourceNames -AppName $AppName -ResourceGroup $ResourceGroup
$rg = $names.ResourceGroup

Write-Host "1. Checking Azure CLI sign-in..." -ForegroundColor Cyan
$account = Invoke-Az @("account", "show", "--output", "json") | ConvertFrom-Json
Write-Host "   Subscription '$($account.name)', app '$AppName'." -ForegroundColor Green

$rgExists = Test-Az @("group", "show", "--name", $rg)
# Exact name: --display-name would also match every app registration whose name only starts with it
$appIds = @((Invoke-Az @("ad", "app", "list", "--filter", "displayName eq '$($names.GitHubApp)'",
                         "--query", "[].appId", "--output", "tsv")) -split "\s+" | Where-Object { $_ })

Write-Host "`nThe following will be PERMANENTLY deleted:" -ForegroundColor Yellow
if ($rgExists) {
    Write-Host "   Resource group '$rg' with every file, record and secret in it:"
    Write-Host (Invoke-Az @("resource", "list", "--resource-group", $rg, "--query", "[].{Name:name, Type:type}", "--output", "table"))
    Write-Host "   Its key vault, purged after the deletion (no recovery)"
} else {
    Write-Host "   Resource group '$rg': not found" -ForegroundColor DarkGray
}
if ($appIds.Count -gt 0) {
    Write-Host "   App registration '$($names.GitHubApp)' ($($appIds -join ', ')), the deploy workflow's sign-in"
} else {
    Write-Host "   App registration '$($names.GitHubApp)': not found" -ForegroundColor DarkGray
}

if (-not $Force) {
    $answer = Read-Host "`nType 'delete' to continue"
    if ($answer -ne "delete") {
        Write-Host "Aborted. Nothing was deleted." -ForegroundColor Yellow
        exit 1
    }
}

Write-Host "`n2. Resource group '$rg' (usually 5-15 minutes)..." -ForegroundColor Cyan
if ($rgExists) {
    Invoke-Az @("group", "delete", "--name", $rg, "--yes") | Out-Null
    Write-Host "   Deleted." -ForegroundColor Green
} else {
    Write-Host "   Not found, skipping." -ForegroundColor DarkGray
}

Write-Host "`n3. Deleted key vaults of '$rg'..." -ForegroundColor Cyan
# Only vaults that were in this resource group: other apps' deleted vaults stay recoverable
$deletedVaults = @(ConvertFrom-JsonList (Invoke-Az @("keyvault", "list-deleted", "--resource-type", "vault", "--output", "json")) |
                   Where-Object { $_.properties.vaultId -match "/resourceGroups/$([regex]::Escape($rg))/" })
if ($deletedVaults.Count -eq 0) {
    Write-Host "   None found." -ForegroundColor DarkGray
}
foreach ($vault in $deletedVaults) {
    Invoke-Az @("keyvault", "purge", "--name", $vault.name) | Out-Null
    Write-Host "   Purged '$($vault.name)'." -ForegroundColor Green
}

Write-Host "`n4. App registration '$($names.GitHubApp)'..." -ForegroundColor Cyan
if ($appIds.Count -eq 0) {
    Write-Host "   Not found, skipping." -ForegroundColor DarkGray
}
foreach ($appId in $appIds) {
    # The service principal first (it holds the roles), then the registration with its federated credentials
    if (Test-Az @("ad", "sp", "show", "--id", $appId)) {
        Invoke-Az @("ad", "sp", "delete", "--id", $appId) | Out-Null
    }
    Invoke-Az @("ad", "app", "delete", "--id", $appId) | Out-Null
    Write-Host "   Deleted '$appId'." -ForegroundColor Green
}

Write-Host "`n=== AZURE TEARDOWN COMPLETE ===" -ForegroundColor Green
Write-Host "Optionally remove these from GitHub (Settings -> Secrets and variables -> Actions):" -ForegroundColor Yellow
Write-Host "Secrets:   AZURE_DEPLOY_CLIENT_ID, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID"
Write-Host "Variable:  AZURE_RESOURCE_GROUP   (APP_NAME and CORS_ALLOW_ORIGINS are still used by the AWS deploy)"
