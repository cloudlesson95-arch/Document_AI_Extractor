# Shared by setup.ps1 and teardown.ps1 (dot-sourced): AWS CLI helpers and the names of this app's AWS resources.

function Get-ResourceNames {
    # Every name starts with the app name, so apps that share an account never touch each other's resources, and
    # teardown.ps1 deletes exactly what setup.ps1 created. .github/workflows/deploy.yml derives the same names.
    param([string]$AppName, [string]$Account, [string]$Region)
    if ($AppName -cnotmatch '^[a-z][a-z0-9-]{1,19}$') {
        throw "-AppName must be 2-20 lowercase letters, digits or hyphens, starting with a letter (it's part of an S3 bucket name)"
    }
    $function = "$AppName-api"
    return @{
        Repository      = "$AppName-api"
        Function        = $function
        FunctionArn     = "arn:aws:lambda:${Region}:${Account}:function:$function"
        LogGroup        = "/aws/lambda/$function"
        LambdaRole      = "$AppName-lambda-role"
        GitHubRole      = "$AppName-github-deploy-role"
        Bucket          = "$AppName-uploads-$Account"
        RecordsTable    = "$AppName-receipts"
        QuotaTable      = "$AppName-upload-counts"
        # Fixed by the backend (AWSSecretProvider.NAME_PREFIX in backend/secrets.py), not by -AppName
        Secret          = "document-ai-extractor/GOOGLE_API_KEY"
        # One per account, shared with every other app that deploys from GitHub Actions
        OidcProviderArn = "arn:aws:iam::${Account}:oidc-provider/token.actions.githubusercontent.com"
    }
}

function Invoke-Aws {
    # Runs the AWS CLI and returns its standard output as one string; throws with the CLI's message if it fails
    param([string[]]$CmdArgs)
    $ErrorActionPreference = "Continue"  # Windows PowerShell turns a native command's stderr into an error under "Stop"
    $result = & aws @CmdArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "aws $($CmdArgs -join ' ') failed:`n$(($result | Out-String).Trim())"
    }
    return (@($result | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] }) -join "`n")
}

function Test-Aws {
    # Runs the AWS CLI and returns whether it succeeded, e.g. whether a describe call found its resource
    param([string[]]$CmdArgs)
    $ErrorActionPreference = "Continue"
    $null = & aws @CmdArgs 2>&1
    return ($LASTEXITCODE -eq 0)
}

function Invoke-AwsWithFile {
    # Writes $Content to a temporary UTF-8 file without a BOM (the AWS CLI rejects one), runs the CLI with "{file}" in
    # the arguments replaced by file://<path>, and deletes the file. Also keeps secrets off the command line.
    param([string]$Content, [string[]]$CmdArgs)
    $path = [System.IO.Path]::GetTempFileName()
    try {
        [System.IO.File]::WriteAllText($path, $Content, (New-Object System.Text.UTF8Encoding($false)))
        return Invoke-Aws ($CmdArgs | ForEach-Object { $_.Replace("{file}", "file://$path") })
    } finally {
        Remove-Item $path -ErrorAction SilentlyContinue
    }
}
