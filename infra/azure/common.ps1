# Shared by setup.ps1 and teardown.ps1 (dot-sourced): Azure CLI helpers and the names of this app's Azure resources.

function Get-ResourceNames {
    # Everything lives in one resource group named after the app, which teardown.ps1 deletes as a whole. main.bicep names
    # the resources inside it; the storage account, registry and vault get a suffix unique to the resource group, since
    # their names are global. .github/workflows/deploy-azure.yml derives the Container App's name from APP_NAME too.
    param([string]$AppName, [string]$ResourceGroup)
    if ($AppName -cnotmatch '^[a-z][a-z0-9]{1,8}$') {
        throw "-AppName must be 2-9 lowercase letters or digits, starting with a letter (it's part of the storage account's name)"
    }
    return @{
        ResourceGroup = if ($ResourceGroup) { $ResourceGroup } else { "$AppName-rg" }
        Deployment    = $AppName  # the Bicep deployment, whose outputs the deploy workflow reads
        ContainerApp  = "$AppName-api"
        GitHubApp     = "$AppName-github-deploy"  # the Entra ID app registration the deploy workflow signs in as
        # AzureKeyVaultSecretProvider's name for GOOGLE_API_KEY: Key Vault names can't contain underscores
        Secret        = "GOOGLE-API-KEY"
    }
}

function Invoke-Az {
    # Runs the Azure CLI and returns its standard output as one string; throws with the CLI's message if it fails
    param([string[]]$CmdArgs)
    $ErrorActionPreference = "Continue"  # Windows PowerShell turns a native command's stderr into an error under "Stop"
    $result = & az @CmdArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "az $($CmdArgs -join ' ') failed:`n$(($result | Out-String).Trim())"
    }
    return (@($result | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] }) -join "`n")
}

function Test-Az {
    # Runs the Azure CLI and returns whether it succeeded, e.g. whether a show command found its resource
    param([string[]]$CmdArgs)
    $ErrorActionPreference = "Continue"
    $null = & az @CmdArgs 2>&1
    return ($LASTEXITCODE -eq 0)
}

function Invoke-AzWithFile {
    # Writes $Content to a temporary UTF-8 file without a BOM, runs the CLI with "{file}" in the arguments replaced by
    # the file's path, and deletes the file. Keeps secrets off the command line.
    param([string]$Content, [string[]]$CmdArgs)
    $path = [System.IO.Path]::GetTempFileName()
    try {
        [System.IO.File]::WriteAllText($path, $Content, (New-Object System.Text.UTF8Encoding($false)))
        return Invoke-Az ($CmdArgs | ForEach-Object { $_.Replace("{file}", $path) })
    } finally {
        Remove-Item $path -ErrorAction SilentlyContinue
    }
}

function ConvertFrom-JsonList {
    # Lists a JSON array's items one by one. Windows PowerShell's ConvertFrom-Json passes an array down the pipeline as
    # a single object, so a Where-Object right after it tests the whole array at once and passes all of it when any
    # item matches: a loop over "this app's deleted vaults" would get every deleted vault in the subscription as one item.
    param([string]$Json)
    $items = $Json | ConvertFrom-Json
    return $items
}

function Invoke-AzUntilAllowed {
    # Runs Invoke-Az (or Invoke-AzWithFile with -Content), retrying while a new role assignment hasn't reached the
    # service yet: Azure can take a few minutes to apply one, and until then the call is refused as forbidden
    param([string[]]$CmdArgs, [string]$Content = "", [int]$Attempts = 18)
    for ($attempt = 1; ; $attempt++) {
        try {
            if ($Content) {
                return Invoke-AzWithFile $Content $CmdArgs
            }
            return Invoke-Az $CmdArgs
        } catch {
            if ($attempt -ge $Attempts -or $_.Exception.Message -notmatch "Forbidden|AuthorizationFailed|does not have (secrets )?(get|set|list) permission") {
                throw
            }
            Write-Host "   Waiting for the new permission to apply ($attempt/$Attempts)..." -ForegroundColor DarkGray
            Start-Sleep -Seconds 10
        }
    }
}
