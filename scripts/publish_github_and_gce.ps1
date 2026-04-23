[CmdletBinding()]
param(
    [string]$GitHubOwner = "lfpadron",
    [string]$GitHubRepo = "GTV-Elevadores-01",
    [string]$Branch = "main",
    [string]$ProjectId = "gtv-elevadores-01",
    [string]$ProjectName = "GTV-Elevadores-01",
    [string]$OrganizationDisplayName = "Lfpadron-org",
    [string]$OrganizationId = "",
    [string]$BillingAccountId = "",
    [switch]$CreateProject,
    [ValidateSet("private", "public")]
    [string]$RepoVisibility = "private",
    [string]$Region = "us-central1",
    [string]$Zone = "us-central1-a",
    [string]$VmName = "gtv-elevadores-01-vm",
    [string]$MachineType = "e2-medium",
    [string]$ServiceName = "gtv-elevadores-01",
    [string]$SecretName = "gtv-elevadores-streamlit-secrets",
    [string]$FirewallRuleName = "allow-gtv-elevadores-8501",
    [string]$CommitMessage = "Prepare Google Cloud deployment",
    [switch]$OpenBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptRoot "..")
$RepoFullName = "$GitHubOwner/$GitHubRepo"
$RepoUrl = "https://github.com/$RepoFullName.git"
$BundlePath = Join-Path $env:TEMP "$ServiceName-deploy.tar.gz"
$RemoteBundlePath = "~/$(Split-Path $BundlePath -Leaf)"
$RemoteSecretsPath = "~/$(Split-Path '.streamlit\secrets.toml' -Leaf)"
$RemoteInstallerPath = "~/install_on_gce.sh"
$AppDir = "/opt/$ServiceName"
$AppUrl = $null

function Assert-Command([string]$CommandName) {
    if (-not (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
        throw "No se encontro el comando requerido: $CommandName"
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        $joined = ($ArgumentList -join " ")
        throw "Fallo el comando: $FilePath $joined"
    }
}

function Test-GitHead {
    & git rev-parse --verify HEAD 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

function Get-GitConfigValue([string]$Key) {
    $value = (& git config --get $Key 2>$null)
    if ($LASTEXITCODE -ne 0) {
        return ""
    }
    return ($value | Out-String).Trim()
}

function Ensure-GitIdentity {
    $currentName = Get-GitConfigValue "user.name"
    $currentEmail = Get-GitConfigValue "user.email"
    if ($currentName -and $currentEmail) {
        return
    }

    $pythonScript = @"
import sys
import tomllib
from pathlib import Path

path = Path('.streamlit/secrets.toml')
if not path.exists():
    raise SystemExit(1)

with path.open('rb') as handle:
    data = tomllib.load(handle)

admin1 = (data.get('seed_users') or {}).get('admin1') or {}
name = (admin1.get('full_name') or '').strip()
email = (admin1.get('email') or '').strip().lower()

if not name or not email:
    raise SystemExit(2)

print(name)
print(email)
"@

    $identity = & py -3 -c $pythonScript
    if ($LASTEXITCODE -ne 0 -or $identity.Count -lt 2) {
        throw "No fue posible resolver user.name y user.email para git. Configura git localmente o completa seed_users.admin1 en .streamlit/secrets.toml."
    }

    $resolvedName = ($identity[0] | Out-String).Trim()
    $resolvedEmail = ($identity[1] | Out-String).Trim()

    Invoke-Checked git @("config", "user.name", $resolvedName)
    Invoke-Checked git @("config", "user.email", $resolvedEmail)
}

function Test-GitStagedChanges {
    & git diff --cached --quiet
    return $LASTEXITCODE -ne 0
}

function Test-GitRemoteExists([string]$RemoteName) {
    & git remote get-url $RemoteName 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

function Test-GitHubRepoExists([string]$FullName) {
    & gh repo view $FullName --json name 1>$null 2>$null
    return $LASTEXITCODE -eq 0
}

function Test-GcpProjectExists([string]$ActiveProjectId) {
    & gcloud projects describe $ActiveProjectId 1>$null 2>$null
    return $LASTEXITCODE -eq 0
}

function Test-GcpSecretExists([string]$ActiveProjectId, [string]$ActiveSecretName) {
    & gcloud secrets describe $ActiveSecretName --project $ActiveProjectId 1>$null 2>$null
    return $LASTEXITCODE -eq 0
}

function Test-FirewallRuleExists([string]$RuleName, [string]$ActiveProjectId) {
    & gcloud compute firewall-rules describe $RuleName --project $ActiveProjectId 1>$null 2>$null
    return $LASTEXITCODE -eq 0
}

function Test-InstanceExists([string]$InstanceName, [string]$ActiveProjectId, [string]$ActiveZone) {
    & gcloud compute instances describe $InstanceName --project $ActiveProjectId --zone $ActiveZone 1>$null 2>$null
    return $LASTEXITCODE -eq 0
}

function Wait-ForUrl([string]$Url, [int]$TimeoutSeconds = 180) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 15
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return
            }
        } catch {
            Start-Sleep -Seconds 5
            continue
        }
    }
    throw "La aplicacion no respondio a tiempo en $Url"
}

Assert-Command git
Assert-Command gh
Assert-Command gcloud
Assert-Command tar

Push-Location $RepoRoot
try {
    if (-not (Test-Path ".streamlit\secrets.toml")) {
        throw "Falta .streamlit\secrets.toml. Debes configurarlo antes de publicar."
    }

    if (-not (Test-Path ".git")) {
        Invoke-Checked git @("init")
    }

    Invoke-Checked git @("checkout", "-B", $Branch)
    Ensure-GitIdentity

    if (-not (Test-GitHubRepoExists $RepoFullName)) {
        $createArgs = @("repo", "create", $RepoFullName, "--$RepoVisibility", "--source", ".", "--remote", "origin")
        Invoke-Checked gh $createArgs
    } elseif (-not (Test-GitRemoteExists "origin")) {
        Invoke-Checked git @("remote", "add", "origin", $RepoUrl)
    } else {
        Invoke-Checked git @("remote", "set-url", "origin", $RepoUrl)
    }

    Invoke-Checked git @("add", ".")

    $hasHead = Test-GitHead
    $hasStagedChanges = Test-GitStagedChanges
    if ($hasStagedChanges -or -not $hasHead) {
        Invoke-Checked git @("commit", "-m", $CommitMessage)
    }

    Invoke-Checked git @("push", "-u", "origin", $Branch)

    if (-not (Test-GcpProjectExists $ProjectId)) {
        if (-not $CreateProject) {
            throw (
                "El proyecto de Google Cloud '$ProjectId' no existe. " +
                "Si quieres que el script lo cree, ejecutalo con -CreateProject " +
                "y proporciona -BillingAccountId. " +
                "La organizacion visible recibida fue '$OrganizationDisplayName', " +
                "pero Google Cloud requiere un OrganizationId numerico para crear el proyecto dentro de una organizacion."
            )
        }
        if (-not $BillingAccountId) {
            throw "Falta -BillingAccountId para crear y activar el proyecto de Google Cloud."
        }

        $createProjectArgs = @("projects", "create", $ProjectId, "--name", $ProjectName)
        if ($OrganizationId) {
            $createProjectArgs += @("--organization", $OrganizationId)
        }
        Invoke-Checked gcloud $createProjectArgs
        Invoke-Checked gcloud @("beta", "billing", "projects", "link", $ProjectId, "--billing-account", $BillingAccountId)
    }

    Invoke-Checked gcloud @("config", "set", "project", $ProjectId)
    Invoke-Checked gcloud @("services", "enable", "compute.googleapis.com", "secretmanager.googleapis.com")

    if (-not (Test-GcpSecretExists $ProjectId $SecretName)) {
        Invoke-Checked gcloud @("secrets", "create", $SecretName, "--project", $ProjectId, "--replication-policy", "automatic")
    }
    Invoke-Checked gcloud @("secrets", "versions", "add", $SecretName, "--project", $ProjectId, "--data-file", ".streamlit\secrets.toml")

    if (-not (Test-FirewallRuleExists $FirewallRuleName $ProjectId)) {
        Invoke-Checked gcloud @(
            "compute", "firewall-rules", "create", $FirewallRuleName,
            "--project", $ProjectId,
            "--allow", "tcp:8501",
            "--direction", "INGRESS",
            "--target-tags", "gtv-elevadores-app",
            "--source-ranges", "0.0.0.0/0"
        )
    }

    if (-not (Test-InstanceExists $VmName $ProjectId $Zone)) {
        Invoke-Checked gcloud @(
            "compute", "instances", "create", $VmName,
            "--project", $ProjectId,
            "--zone", $Zone,
            "--machine-type", $MachineType,
            "--image-family", "debian-12",
            "--image-project", "debian-cloud",
            "--boot-disk-size", "30GB",
            "--tags", "gtv-elevadores-app",
            "--labels", "app=gtv-elevadores-01,owner=lfpadron-org"
        )
    }

    if (Test-Path $BundlePath) {
        Remove-Item $BundlePath -Force
    }

    Invoke-Checked tar @(
        "-czf", $BundlePath,
        "--exclude=.git",
        "--exclude=.venv",
        "--exclude=__pycache__",
        "--exclude=.env",
        "--exclude=.streamlit/secrets.toml",
        "--exclude=data",
        "--exclude=*.pyc",
        "-C", $RepoRoot,
        "."
    )

    Invoke-Checked gcloud @("compute", "scp", "--project", $ProjectId, "--zone", $Zone, $BundlePath, "${VmName}:$RemoteBundlePath")
    Invoke-Checked gcloud @("compute", "scp", "--project", $ProjectId, "--zone", $Zone, ".streamlit\secrets.toml", "${VmName}:$RemoteSecretsPath")
    Invoke-Checked gcloud @("compute", "scp", "--project", $ProjectId, "--zone", $Zone, "scripts\install_on_gce.sh", "${VmName}:$RemoteInstallerPath")

    $remoteCommand = @(
        "chmod +x $RemoteInstallerPath",
        "sudo $RemoteInstallerPath --bundle $RemoteBundlePath --secrets $RemoteSecretsPath --app-dir $AppDir --service-name $ServiceName"
    ) -join " && "

    Invoke-Checked gcloud @("compute", "ssh", $VmName, "--project", $ProjectId, "--zone", $Zone, "--command", $remoteCommand)

    $externalIp = (& gcloud compute instances describe $VmName --project $ProjectId --zone $Zone --format "get(networkInterfaces[0].accessConfigs[0].natIP)").Trim()
    if (-not $externalIp) {
        throw "No fue posible obtener la IP externa de la VM."
    }

    $AppUrl = "http://$externalIp:8501"
    Wait-ForUrl -Url $AppUrl -TimeoutSeconds 240

    Write-Host ""
    Write-Host "Publicacion completada."
    Write-Host "GitHub: https://github.com/$RepoFullName"
    Write-Host "Google Cloud project: $ProjectId"
    Write-Host "VM: $VmName"
    Write-Host "Aplicacion: $AppUrl"
    Write-Host "Secret Manager: $SecretName"

    if ($OpenBrowser) {
        Start-Process $AppUrl
    }
}
finally {
    Pop-Location
    if (Test-Path $BundlePath) {
        Remove-Item $BundlePath -Force
    }
}
