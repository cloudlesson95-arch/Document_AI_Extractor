# ==============================================================================
# Azure setup for Document AI Extractor: the resources, roles and GitHub sign-in
# that .github/workflows/deploy-azure.yml needs. The workflow creates the Container
# App itself, from the first image it pushes.
# ==============================================================================
# Everything lives in one resource group named after -AppName (see common.ps1), so
# teardown.ps1 deletes exactly this app. The Entra ID app registration that the
# deploy workflow signs in as is the one thing outside it.
# Safe to re-run: main.bicep is deployed again (existing resources are kept, their
# settings and roles written again) and the GitHub sign-in is rewritten, so a rerun
# also applies a new -GitHubRepo.
param(
    [string]$Location = "eastus",
    [string]$AppName = "docai",
    [string]$ResourceGroup = "",
    [string]$GitHubRepo = "cloudlesson95-arch/Document_AI_Extractor"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

if ($GitHubRepo -notmatch '^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$') {
    throw "-GitHubRepo must look like owner/name, got '$GitHubRepo'"
}
$names = Get-ResourceNames -AppName $AppName -ResourceGroup $ResourceGroup
$rg = $names.ResourceGroup

Write-Host "1. Checking Azure CLI sign-in..." -ForegroundColor Cyan
$account = Invoke-Az @("account", "show", "--output", "json") | ConvertFrom-Json
# Your own object ID: main.bicep lets you write the vault's secrets, for step 5
$operatorId = (Invoke-Az @("ad", "signed-in-user", "show", "--query", "id", "--output", "tsv")).Trim()
Write-Host "   Subscription '$($account.name)', signed in as $($account.user.name), app '$AppName'." -ForegroundColor Green

Write-Host "`n2. Resource group '$rg' in $Location..." -ForegroundColor Cyan
if (Test-Az @("group", "show", "--name", $rg)) {
    $existingLocation = (Invoke-Az @("group", "show", "--name", $rg, "--query", "location", "--output", "tsv")).Trim()
    if ($existingLocation -ne $Location) {
        throw "Resource group '$rg' is in $existingLocation, not $Location; pass -Location $existingLocation"
    }
    Write-Host "   Already exists." -ForegroundColor Green
} else {
    Invoke-Az @("group", "create", "--name", $rg, "--location", $Location) | Out-Null
    Write-Host "   Created." -ForegroundColor Green
}

Write-Host "`n3. App registration '$($names.GitHubApp)' for the deploy workflow of $GitHubRepo..." -ForegroundColor Cyan
# Exact name: --display-name would also match every app registration whose name only starts with it
$appIds = @((Invoke-Az @("ad", "app", "list", "--filter", "displayName eq '$($names.GitHubApp)'",
                         "--query", "[].appId", "--output", "tsv")) -split "\s+" | Where-Object { $_ })
if ($appIds.Count -gt 1) {
    throw "Several app registrations are named '$($names.GitHubApp)' ($($appIds -join ', ')). Delete the extra ones, then rerun setup.ps1."
}
if ($appIds.Count -eq 1) {
    $appId = $appIds[0]
    Write-Host "   Already exists." -ForegroundColor Green
} else {
    $appId = (Invoke-Az @("ad", "app", "create", "--display-name", $names.GitHubApp, "--sign-in-audience", "AzureADMyOrg",
                          "--query", "appId", "--output", "tsv")).Trim()
    Write-Host "   Created." -ForegroundColor Green
}
# Roles are given to the registration's service principal
$deployPrincipalId = (Invoke-Az @("ad", "sp", "list", "--filter", "appId eq '$appId'", "--query", "[0].id", "--output", "tsv")).Trim()
if (-not $deployPrincipalId) {
    $deployPrincipalId = (Invoke-Az @("ad", "sp", "create", "--id", $appId, "--query", "id", "--output", "tsv")).Trim()
}

# GitHub's token names the repository in its subject. Repositories created since 2026-07-15 use the immutable form
# repo:OWNER@OWNER_ID/REPO@REPO_ID:ref:refs/heads/main; older ones repo:OWNER/REPO:ref:refs/heads/main. Entra ID
# matches a subject exactly, so each form gets its own federated credential, for the main branch only: other
# branches, pull requests and other repositories can't sign in.
$owner, $repo = $GitHubRepo.Split("/")
$wanted = [ordered]@{}
try {
    $repoInfo = Invoke-RestMethod -Uri "https://api.github.com/repos/$GitHubRepo" -UserAgent "docai-setup"
    $owner, $repo = $repoInfo.full_name.Split("/")  # GitHub's own spelling, which the subject uses
    $wanted["github-main-ids"] = "repo:${owner}@$($repoInfo.owner.id)/${repo}@$($repoInfo.id):ref:refs/heads/main"
} catch {
    Write-Host "   Not on GitHub yet (or private): trusting it by name only. Rerun setup.ps1 once it exists to trust its IDs too." -ForegroundColor Yellow
}
$wanted["github-main"] = "repo:${owner}/${repo}:ref:refs/heads/main"
$issuer = "https://token.actions.githubusercontent.com"
$credentials = Invoke-Az @("ad", "app", "federated-credential", "list", "--id", $appId, "--output", "json")
foreach ($name in $wanted.Keys) {
    $current = ConvertFrom-JsonList $credentials | Where-Object { $_.name -eq $name }
    if ($current -and $current.subject -eq $wanted[$name] -and $current.issuer -eq $issuer -and
        (@($current.audiences) -join ",") -eq "api://AzureADTokenExchange") {
        Write-Host "   Federated credential '$name' already trusts $($wanted[$name])." -ForegroundColor Green
        continue
    }
    $credential = @{ name = $name; issuer = $issuer; subject = $wanted[$name]; audiences = @("api://AzureADTokenExchange")
                     description = "GitHub Actions on the main branch of $GitHubRepo" } | ConvertTo-Json
    if ($current) {
        Invoke-AzWithFile $credential @("ad", "app", "federated-credential", "update", "--id", $appId,
                                        "--federated-credential-id", $current.id, "--parameters", "{file}") | Out-Null
    } else {
        Invoke-AzWithFile $credential @("ad", "app", "federated-credential", "create", "--id", $appId, "--parameters", "{file}") | Out-Null
    }
    Write-Host "   Federated credential '$name' now trusts $($wanted[$name])." -ForegroundColor Green
}

Write-Host "`n4. Resources from main.bicep (the first run takes a few minutes)..." -ForegroundColor Cyan
$outputs = Invoke-Az @("deployment", "group", "create", "--resource-group", $rg, "--name", $names.Deployment,
                       "--template-file", (Join-Path $PSScriptRoot "main.bicep"),
                       "--parameters", "appName=$AppName", "deployPrincipalId=$deployPrincipalId", "operatorPrincipalId=$operatorId",
                       "--query", "properties.outputs", "--output", "json") | ConvertFrom-Json
$vaultName = $outputs.keyVaultName.value
Write-Host "   Storage account '$($outputs.storageAccount.value)', registry '$($outputs.registryName.value)', key vault '$vaultName'." -ForegroundColor Green

Write-Host "`n5. Key Vault secret '$($names.Secret)' (the Gemini API key)..." -ForegroundColor Cyan
# Step 4 just gave you the role that reads and writes it; Azure can take a few minutes to apply a new role
$secretExists = [bool](Invoke-AzUntilAllowed @("keyvault", "secret", "list", "--vault-name", $vaultName,
                                               "--query", "[?ends_with(id, '/secrets/$($names.Secret)')].id | [0]", "--output", "tsv")).Trim()
$prompt = if ($secretExists) { "   GOOGLE_API_KEY (Enter keeps the stored one)" } else { "   GOOGLE_API_KEY (Enter skips; uploads fail until it's set)" }
$secureKey = Read-Host $prompt -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $googleKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
if ($googleKey) {
    # Read from a temporary file, so the key never appears on a command line
    Invoke-AzUntilAllowed -Content $googleKey -CmdArgs @("keyvault", "secret", "set", "--vault-name", $vaultName,
                                                         "--name", $names.Secret, "--file", "{file}", "--encoding", "utf-8") | Out-Null
    Write-Host "   Stored." -ForegroundColor Green
    $secretExists = $true
} elseif ($secretExists) {
    Write-Host "   Kept the stored value." -ForegroundColor Green
} else {
    Write-Host "   Skipped: rerun setup.ps1 to set it." -ForegroundColor Yellow
}
$googleKey = $null

Write-Host "`n6. The app's access to the Gemini key..." -ForegroundColor Cyan
if ($secretExists) {
    # Scoped to this one secret, which only exists once stored, so main.bicep can't grant it. 4633458b-... is the
    # built-in role "Key Vault Secrets User": read a secret's value, nothing else.
    try {
        Invoke-Az @("role", "assignment", "create", "--assignee-object-id", $outputs.identityPrincipalId.value,
                    "--assignee-principal-type", "ServicePrincipal", "--role", "4633458b-17de-408a-b874-0445c86b69e6",
                    "--scope", "$($outputs.keyVaultId.value)/secrets/$($names.Secret)") | Out-Null
    } catch {
        if ($_.Exception.Message -notmatch "RoleAssignmentExists|already exists") {
            throw
        }
    }
    Write-Host "   The app's identity may read '$($names.Secret)', and no other secret." -ForegroundColor Green
} else {
    Write-Host "   Skipped until the secret exists." -ForegroundColor Yellow
}

Write-Host "`n=== AZURE SETUP COMPLETE ===" -ForegroundColor Green
Write-Host "In GitHub: $GitHubRepo -> Settings -> Secrets and variables -> Actions." -ForegroundColor Yellow
Write-Host "Repository secrets:"
Write-Host "   AZURE_DEPLOY_CLIENT_ID   $appId"
Write-Host "   AZURE_TENANT_ID          $($account.tenantId)"
Write-Host "   AZURE_SUBSCRIPTION_ID    $($account.id)"
Write-Host "Repository variables:"
Write-Host "   AZURE_RESOURCE_GROUP     $rg"
Write-Host "   APP_NAME                 $AppName   (shared with the AWS deploy: both workflows read it)"
Write-Host "   CORS_ALLOW_ORIGINS       already set for the AWS deploy; the Azure deploy uses the same origins"
Write-Host "Then run the 'Deploy to Azure' workflow on main (Actions tab). Its summary shows the API URL."
