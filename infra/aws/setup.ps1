# ==============================================================================
# AWS setup for Document AI Extractor: the resources and IAM roles that
# .github/workflows/deploy.yml needs. The workflow creates the Lambda function
# itself, from the first image it pushes.
# ==============================================================================
# Every resource is named after -AppName (see common.ps1), so another app's setup
# or teardown in the same account never touches these, and this one never touches
# theirs. The GitHub OIDC provider is the exception: there is one per account.
# Safe to re-run: existing resources are kept, while the IAM policies, the GitHub
# trust policy and the bucket, repository and log settings are written again, so
# a rerun also applies a new -GitHubRepo.
param(
    [string]$Region = "us-east-1",
    [string]$AppName = "docai",
    [string]$GitHubRepo = "cloudlesson95-arch/Document_AI_Extractor"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

if ($GitHubRepo -notmatch '^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$') {
    throw "-GitHubRepo must look like owner/name, got '$GitHubRepo'"
}

function Set-IamRole {
    # Creates the role if it's missing, then writes its trust policy and its one inline policy, so a rerun applies changes
    param([string]$RoleName, [string]$TrustPolicy, [string]$PolicyName, [string]$Policy)
    if (Test-Aws @("iam", "get-role", "--role-name", $RoleName)) {
        Invoke-AwsWithFile $TrustPolicy @("iam", "update-assume-role-policy", "--role-name", $RoleName, "--policy-document", "{file}") | Out-Null
        Write-Host "   Role exists; trust policy written." -ForegroundColor Green
    } else {
        Invoke-AwsWithFile $TrustPolicy @("iam", "create-role", "--role-name", $RoleName, "--assume-role-policy-document", "{file}") | Out-Null
        Write-Host "   Created the role." -ForegroundColor Green
    }
    Invoke-AwsWithFile $Policy @("iam", "put-role-policy", "--role-name", $RoleName, "--policy-name", $PolicyName, "--policy-document", "{file}") | Out-Null
    Write-Host "   Permissions written ($PolicyName)." -ForegroundColor Green
}

Write-Host "1. Checking AWS CLI authentication..." -ForegroundColor Cyan
$account = (Invoke-Aws @("sts", "get-caller-identity", "--query", "Account", "--output", "text")).Trim()
$names = Get-ResourceNames -AppName $AppName -Account $account -Region $Region
Write-Host "   Account $account, region $Region, app '$AppName'." -ForegroundColor Green

Write-Host "`n2. ECR repository '$($names.Repository)' for the images..." -ForegroundColor Cyan
if (Test-Aws @("ecr", "describe-repositories", "--repository-names", $names.Repository, "--region", $Region)) {
    Write-Host "   Already exists." -ForegroundColor Green
} else {
    Invoke-Aws @("ecr", "create-repository", "--repository-name", $names.Repository,
                 "--image-scanning-configuration", "scanOnPush=true", "--region", $Region) | Out-Null
    Write-Host "   Created (images are scanned for known vulnerabilities on push)." -ForegroundColor Green
}
# Lambda pulls the image with its service principal
$repositoryPolicy = @"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "LambdaImagePull",
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
  }]
}
"@
Invoke-AwsWithFile $repositoryPolicy @("ecr", "set-repository-policy", "--repository-name", $names.Repository,
                                       "--policy-text", "{file}", "--region", $Region) | Out-Null
# Each deploy pushes an image tagged with its commit; the last few stay for a rollback
$lifecyclePolicy = @"
{
  "rules": [{
    "rulePriority": 1,
    "description": "Keep the 5 most recent images",
    "selection": {"tagStatus": "any", "countType": "imageCountMoreThan", "countNumber": 5},
    "action": {"type": "expire"}
  }]
}
"@
Invoke-AwsWithFile $lifecyclePolicy @("ecr", "put-lifecycle-policy", "--repository-name", $names.Repository,
                                      "--lifecycle-policy-text", "{file}", "--region", $Region) | Out-Null
Write-Host "   Lambda may pull; only the 5 newest images are kept." -ForegroundColor Green

Write-Host "`n3. S3 bucket '$($names.Bucket)' for the uploaded files..." -ForegroundColor Cyan
if (Test-Aws @("s3api", "head-bucket", "--bucket", $names.Bucket)) {
    Write-Host "   Already exists." -ForegroundColor Green
} else {
    $createBucket = @("s3api", "create-bucket", "--bucket", $names.Bucket, "--region", $Region)
    if ($Region -ne "us-east-1") {
        $createBucket += @("--create-bucket-configuration", "LocationConstraint=$Region")
    }
    Invoke-Aws $createBucket | Out-Null
    Write-Host "   Created." -ForegroundColor Green
}
# The API serves the files itself, so the bucket is never public. S3 encrypts objects at rest by default.
Invoke-Aws @("s3api", "put-public-access-block", "--bucket", $names.Bucket, "--public-access-block-configuration",
             "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true") | Out-Null
Write-Host "   Public access blocked." -ForegroundColor Green

Write-Host "`n4. DynamoDB tables (on-demand capacity)..." -ForegroundColor Cyan
# Records are keyed by id, the daily upload counts by day
foreach ($table in @(@{ Name = $names.RecordsTable; Key = "id" }, @{ Name = $names.QuotaTable; Key = "day" })) {
    if (Test-Aws @("dynamodb", "describe-table", "--table-name", $table.Name, "--region", $Region)) {
        Write-Host "   '$($table.Name)' already exists." -ForegroundColor Green
    } else {
        Invoke-Aws @("dynamodb", "create-table", "--table-name", $table.Name, "--billing-mode", "PAY_PER_REQUEST",
                     "--attribute-definitions", "AttributeName=$($table.Key),AttributeType=S",
                     "--key-schema", "AttributeName=$($table.Key),KeyType=HASH", "--region", $Region) | Out-Null
        Invoke-Aws @("dynamodb", "wait", "table-exists", "--table-name", $table.Name, "--region", $Region) | Out-Null
        Write-Host "   Created '$($table.Name)'." -ForegroundColor Green
    }
}
# DynamoDB deletes a day's count some time after its expires_at (backend/quota/dynamo.py sets it a week ahead)
$ttlStatus = Invoke-Aws @("dynamodb", "describe-time-to-live", "--table-name", $names.QuotaTable,
                          "--query", "TimeToLiveDescription.TimeToLiveStatus", "--output", "text", "--region", $Region)
if ($ttlStatus.Trim() -notin @("ENABLED", "ENABLING")) {
    Invoke-Aws @("dynamodb", "update-time-to-live", "--table-name", $names.QuotaTable,
                 "--time-to-live-specification", "Enabled=true,AttributeName=expires_at", "--region", $Region) | Out-Null
}
Write-Host "   Old daily counts expire on their own." -ForegroundColor Green

Write-Host "`n5. CloudWatch log group '$($names.LogGroup)'..." -ForegroundColor Cyan
# Created here rather than by Lambda, so the function's role needs no logs:CreateLogGroup, and the logs expire
$found = Invoke-Aws @("logs", "describe-log-groups", "--log-group-name-prefix", $names.LogGroup,
                      "--query", "length(logGroups[?logGroupName=='$($names.LogGroup)'])", "--output", "text", "--region", $Region)
if ($found.Trim() -eq "0") {
    Invoke-Aws @("logs", "create-log-group", "--log-group-name", $names.LogGroup, "--region", $Region) | Out-Null
}
Invoke-Aws @("logs", "put-retention-policy", "--log-group-name", $names.LogGroup, "--retention-in-days", "30", "--region", $Region) | Out-Null
Write-Host "   Logs are kept for 30 days." -ForegroundColor Green

Write-Host "`n6. Secrets Manager secret '$($names.Secret)' (the Gemini API key)..." -ForegroundColor Cyan
$secretExists = Test-Aws @("secretsmanager", "describe-secret", "--secret-id", $names.Secret, "--region", $Region)
$prompt = if ($secretExists) { "   GOOGLE_API_KEY (Enter keeps the stored one)" } else { "   GOOGLE_API_KEY (Enter skips; uploads fail until it's set)" }
$secureKey = Read-Host $prompt -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $googleKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
if ($googleKey -and $secretExists) {
    Invoke-AwsWithFile $googleKey @("secretsmanager", "put-secret-value", "--secret-id", $names.Secret,
                                    "--secret-string", "{file}", "--region", $Region) | Out-Null
    Write-Host "   Stored the new value." -ForegroundColor Green
} elseif ($googleKey) {
    Invoke-AwsWithFile $googleKey @("secretsmanager", "create-secret", "--name", $names.Secret,
                                    "--secret-string", "{file}", "--region", $Region) | Out-Null
    Write-Host "   Created." -ForegroundColor Green
} elseif ($secretExists) {
    Write-Host "   Kept the stored value." -ForegroundColor Green
} else {
    Write-Host "   Skipped: rerun setup.ps1 to set it." -ForegroundColor Yellow
}
$googleKey = $null

Write-Host "`n7. IAM role '$($names.LambdaRole)' for the Lambda function..." -ForegroundColor Cyan
$lambdaTrust = @"
{
  "Version": "2012-10-17",
  "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]
}
"@
# Exactly what the backend calls, on this app's resources only
$runtimePolicy = @"
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid": "Logs", "Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
     "Resource": "arn:aws:logs:${Region}:${account}:log-group:$($names.LogGroup):*"},
    {"Sid": "UploadedFiles", "Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"],
     "Resource": "arn:aws:s3:::$($names.Bucket)/receipts/*"},
    {"Sid": "MissingFilesAnswer404NotAccessDenied", "Effect": "Allow", "Action": "s3:ListBucket",
     "Resource": "arn:aws:s3:::$($names.Bucket)"},
    {"Sid": "Records", "Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Scan"],
     "Resource": "arn:aws:dynamodb:${Region}:${account}:table/$($names.RecordsTable)"},
    {"Sid": "DailyUploadCounts", "Effect": "Allow", "Action": "dynamodb:UpdateItem",
     "Resource": "arn:aws:dynamodb:${Region}:${account}:table/$($names.QuotaTable)"},
    {"Sid": "GeminiKey", "Effect": "Allow", "Action": "secretsmanager:GetSecretValue",
     "Resource": "arn:aws:secretsmanager:${Region}:${account}:secret:$($names.Secret)-??????"}
  ]
}
"@
Set-IamRole -RoleName $names.LambdaRole -TrustPolicy $lambdaTrust -PolicyName "$AppName-runtime" -Policy $runtimePolicy
$lambdaRoleArn = "arn:aws:iam::${account}:role/$($names.LambdaRole)"

Write-Host "`n8. GitHub Actions OIDC provider (one per account, shared with other apps)..." -ForegroundColor Cyan
if (Test-Aws @("iam", "get-open-id-connect-provider", "--open-id-connect-provider-arn", $names.OidcProviderArn)) {
    Write-Host "   Already exists." -ForegroundColor Green
} else {
    Invoke-Aws @("iam", "create-open-id-connect-provider", "--url", "https://token.actions.githubusercontent.com",
                 "--client-id-list", "sts.amazonaws.com", "--thumbprint-list",
                 "6938fd5d98bab03faadb97b34396831e3780aea1", "1c58a21d81938b15d7f8d59bb29c1583fd2ec1cf",
                 "74966d2e0878180753200c682b13280058e57f20") | Out-Null
    Write-Host "   Created." -ForegroundColor Green
}

Write-Host "`n9. IAM role '$($names.GitHubRole)' for the deploy workflow of $GitHubRepo..." -ForegroundColor Cyan
# GitHub's token names the repository in its subject. Repositories created since 2026-07-15 use the immutable form
# repo:OWNER@OWNER_ID/REPO@REPO_ID:ref:refs/heads/main; older ones repo:OWNER/REPO:ref:refs/heads/main. Both are
# trusted, for the main branch only: other branches, pull requests and other repositories can't deploy.
$owner, $repo = $GitHubRepo.Split("/")
try {
    $repoInfo = Invoke-RestMethod -Uri "https://api.github.com/repos/$GitHubRepo" -UserAgent "docai-setup"
    $owner, $repo = $repoInfo.full_name.Split("/")  # GitHub's own spelling, which the subject uses
    $idSubject = "repo:${owner}@$($repoInfo.owner.id)/${repo}@$($repoInfo.id):ref:refs/heads/main"
    Write-Host "   Found the repository on GitHub; trusting its IDs." -ForegroundColor Green
} catch {
    # '@' can't appear in GitHub names, so this still pins the owner and the repository by name, though not by ID
    $idSubject = "repo:${owner}@*/${repo}@*:ref:refs/heads/main"
    Write-Host "   Not on GitHub yet (or private): trusting it by name. Rerun setup.ps1 once it exists to pin its IDs." -ForegroundColor Yellow
}
$nameSubject = "repo:${owner}/${repo}:ref:refs/heads/main"
$githubTrust = @"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "$($names.OidcProviderArn)"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"},
      "StringLike": {"token.actions.githubusercontent.com:sub": ["$nameSubject", "$idSubject"]}
    }
  }]
}
"@
# Push this app's images, create or update this app's function, and hand it this app's role; nothing else
$deployPolicy = @"
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid": "EcrLogin", "Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
    {"Sid": "PushImages", "Effect": "Allow",
     "Action": ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
                "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
     "Resource": "arn:aws:ecr:${Region}:${account}:repository/$($names.Repository)"},
    {"Sid": "DeployFunction", "Effect": "Allow",
     "Action": ["lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:CreateFunction",
                "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration",
                "lambda:GetFunctionUrlConfig", "lambda:CreateFunctionUrlConfig", "lambda:AddPermission"],
     "Resource": "$($names.FunctionArn)"},
    {"Sid": "PassTheFunctionRoleToLambdaOnly", "Effect": "Allow", "Action": "iam:PassRole",
     "Resource": "$lambdaRoleArn",
     "Condition": {"StringEquals": {"iam:PassedToService": "lambda.amazonaws.com"}}}
  ]
}
"@
Set-IamRole -RoleName $names.GitHubRole -TrustPolicy $githubTrust -PolicyName "$AppName-deploy" -Policy $deployPolicy
$githubRoleArn = "arn:aws:iam::${account}:role/$($names.GitHubRole)"

Write-Host "`n=== AWS SETUP COMPLETE ===" -ForegroundColor Green
Write-Host "In GitHub: $GitHubRepo -> Settings -> Secrets and variables -> Actions." -ForegroundColor Yellow
Write-Host "Repository secret:"
Write-Host "   AWS_ROLE_TO_ASSUME   $githubRoleArn"
Write-Host "Repository variables:"
Write-Host "   AWS_REGION           $Region"
Write-Host "   APP_NAME             $AppName"
Write-Host "   CORS_ALLOW_ORIGINS   https://<your Vercel project>.vercel.app http://localhost:3000   (spaces, not commas)"
Write-Host "Then run the 'Deploy to AWS' workflow on main (Actions tab). Its summary shows the API URL for Vercel."
