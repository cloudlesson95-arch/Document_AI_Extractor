# ==============================================================================
# AWS teardown for Document AI Extractor: deletes what infra/aws/setup.ps1 and
# the deploy workflow created for -AppName, and nothing else.
# ==============================================================================
# Only resources named after -AppName (see common.ps1) are deleted, so another
# app's resources in the same account stay untouched. The GitHub OIDC provider is
# shared by every app in the account: it's kept unless -DeleteOidcProvider is
# passed, and even then only deleted when no other IAM role still trusts it.
# Safe to re-run: resources that are already gone are skipped.
param(
    [string]$Region = "us-east-1",
    [string]$AppName = "docai",
    [switch]$KeepSecret,
    [switch]$DeleteOidcProvider,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

function Remove-AwsResource {
    # Runs a delete command; a resource that's already gone counts as deleted
    param([string]$Description, [string[]]$CmdArgs)
    $ErrorActionPreference = "Continue"
    $output = & aws @CmdArgs 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "   Deleted $Description." -ForegroundColor Green
    } elseif (($output | Out-String) -match "NotFound|NoSuchEntity|NoSuchBucket|does not exist") {
        Write-Host "   $Description not found, skipping." -ForegroundColor DarkGray
    } else {
        throw "Failed to delete $Description (aws $($CmdArgs -join ' ')):`n$(($output | Out-String).Trim())"
    }
}

function Remove-IamRole {
    # Policies have to go before the role
    param([string]$RoleName)
    if (-not (Test-Aws @("iam", "get-role", "--role-name", $RoleName))) {
        Write-Host "   IAM role '$RoleName' not found, skipping." -ForegroundColor DarkGray
        return
    }
    $attached = Invoke-Aws @("iam", "list-attached-role-policies", "--role-name", $RoleName,
                             "--query", "AttachedPolicies[].PolicyArn", "--output", "text")
    foreach ($policyArn in ($attached -split "\s+" | Where-Object { $_ -and $_ -ne "None" })) {
        Invoke-Aws @("iam", "detach-role-policy", "--role-name", $RoleName, "--policy-arn", $policyArn) | Out-Null
    }
    $inline = Invoke-Aws @("iam", "list-role-policies", "--role-name", $RoleName, "--query", "PolicyNames", "--output", "text")
    foreach ($policyName in ($inline -split "\s+" | Where-Object { $_ -and $_ -ne "None" })) {
        Invoke-Aws @("iam", "delete-role-policy", "--role-name", $RoleName, "--policy-name", $policyName) | Out-Null
    }
    Invoke-Aws @("iam", "delete-role", "--role-name", $RoleName) | Out-Null
    Write-Host "   Deleted IAM role '$RoleName'." -ForegroundColor Green
}

Write-Host "1. Checking AWS CLI authentication..." -ForegroundColor Cyan
$account = (Invoke-Aws @("sts", "get-caller-identity", "--query", "Account", "--output", "text")).Trim()
$names = Get-ResourceNames -AppName $AppName -Account $account -Region $Region
Write-Host "   Account $account, region $Region, app '$AppName'." -ForegroundColor Green

Write-Host "`nThe following resources of '$AppName' will be PERMANENTLY deleted:" -ForegroundColor Yellow
Write-Host "   Lambda function + Function URL:    $($names.Function)"
Write-Host "   CloudWatch log group:              $($names.LogGroup)"
Write-Host "   ECR repository (all images):       $($names.Repository)"
Write-Host "   S3 bucket (every uploaded file):   $($names.Bucket)"
Write-Host "   DynamoDB tables (every record):    $($names.RecordsTable), $($names.QuotaTable)"
if (-not $KeepSecret) {
    Write-Host "   Secrets Manager (no recovery):     $($names.Secret)"
}
Write-Host "   IAM roles:                         $($names.LambdaRole), $($names.GitHubRole)"
if ($DeleteOidcProvider) {
    Write-Host "   GitHub OIDC provider, unless another IAM role still trusts it"
}

if (-not $Force) {
    $answer = Read-Host "`nType 'delete' to continue"
    if ($answer -ne "delete") {
        Write-Host "Aborted. Nothing was deleted." -ForegroundColor Yellow
        exit 1
    }
}

Write-Host "`n2. Lambda function (its Function URL and permissions go with it)..." -ForegroundColor Cyan
Remove-AwsResource "Lambda function '$($names.Function)'" @("lambda", "delete-function", "--function-name", $names.Function, "--region", $Region)

Write-Host "`n3. CloudWatch log group..." -ForegroundColor Cyan
Remove-AwsResource "log group '$($names.LogGroup)'" @("logs", "delete-log-group", "--log-group-name", $names.LogGroup, "--region", $Region)

Write-Host "`n4. ECR repository and its images..." -ForegroundColor Cyan
Remove-AwsResource "ECR repository '$($names.Repository)'" @("ecr", "delete-repository", "--repository-name", $names.Repository, "--force", "--region", $Region)

Write-Host "`n5. S3 bucket and every uploaded file..." -ForegroundColor Cyan
if (Test-Aws @("s3api", "head-bucket", "--bucket", $names.Bucket)) {
    # Only an empty bucket can be deleted. Versions are listed too, in case versioning was ever turned on.
    $listingJson = Invoke-Aws @("s3api", "list-object-versions", "--bucket", $names.Bucket, "--output", "json")
    $listing = if ($listingJson) { $listingJson | ConvertFrom-Json } else { $null }
    $objects = @(@($listing.Versions) + @($listing.DeleteMarkers) | Where-Object { $_ } |
                 ForEach-Object { @{ Key = $_.Key; VersionId = $_.VersionId } })
    for ($i = 0; $i -lt $objects.Count; $i += 1000) {  # delete-objects takes at most 1000 at a time
        $batch = @{ Objects = @($objects[$i..([Math]::Min($i + 999, $objects.Count - 1))]); Quiet = $true } | ConvertTo-Json -Depth 4
        Invoke-AwsWithFile $batch @("s3api", "delete-objects", "--bucket", $names.Bucket, "--delete", "{file}") | Out-Null
    }
    Invoke-Aws @("s3api", "delete-bucket", "--bucket", $names.Bucket, "--region", $Region) | Out-Null
    Write-Host "   Deleted S3 bucket '$($names.Bucket)' ($($objects.Count) objects)." -ForegroundColor Green
} else {
    Write-Host "   S3 bucket '$($names.Bucket)' not found, skipping." -ForegroundColor DarkGray
}

Write-Host "`n6. DynamoDB tables and every record..." -ForegroundColor Cyan
foreach ($table in @($names.RecordsTable, $names.QuotaTable)) {
    Remove-AwsResource "DynamoDB table '$table'" @("dynamodb", "delete-table", "--table-name", $table, "--region", $Region)
}

Write-Host "`n7. Secrets Manager secret..." -ForegroundColor Cyan
if ($KeepSecret) {
    Write-Host "   Kept '$($names.Secret)' (-KeepSecret)." -ForegroundColor DarkGray
} else {
    # Immediately, without the recovery window, so setup.ps1 can create it again right away
    Remove-AwsResource "secret '$($names.Secret)'" @("secretsmanager", "delete-secret", "--secret-id", $names.Secret,
                                                     "--force-delete-without-recovery", "--region", $Region)
}

Write-Host "`n8. IAM roles..." -ForegroundColor Cyan
Remove-IamRole $names.LambdaRole
Remove-IamRole $names.GitHubRole

Write-Host "`n9. GitHub OIDC provider (shared by every app in the account)..." -ForegroundColor Cyan
if (-not $DeleteOidcProvider) {
    Write-Host "   Kept. Pass -DeleteOidcProvider to delete it once no app in this account deploys from GitHub Actions." -ForegroundColor DarkGray
} else {
    # Deleting it would break the deploys of every app whose role still trusts it
    $trusting = Invoke-Aws @("iam", "list-roles", "--query",
                             "Roles[?contains(to_string(AssumeRolePolicyDocument), 'token.actions.githubusercontent.com')].RoleName",
                             "--output", "text")
    $others = @($trusting -split "\s+" | Where-Object { $_ -and $_ -ne "None" })
    if ($others.Count -gt 0) {
        Write-Host "   Kept: still trusted by $($others -join ', ')." -ForegroundColor Yellow
    } else {
        Remove-AwsResource "GitHub OIDC provider" @("iam", "delete-open-id-connect-provider", "--open-id-connect-provider-arn", $names.OidcProviderArn)
    }
}

Write-Host "`n=== AWS TEARDOWN COMPLETE ===" -ForegroundColor Green
Write-Host "Optionally remove these from GitHub (Settings -> Secrets and variables -> Actions):" -ForegroundColor Yellow
Write-Host "Secret:    AWS_ROLE_TO_ASSUME"
Write-Host "Variables: AWS_REGION, APP_NAME, CORS_ALLOW_ORIGINS"
