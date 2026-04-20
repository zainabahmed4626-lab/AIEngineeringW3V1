param(
  [Parameter(Mandatory = $true)]
  [string]$EnvFile,

  [Parameter(Mandatory = $true)]
  [string]$Command,

  [Parameter(Mandatory = $false)]
  [string[]]$Arguments = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Import-DotEnvFile {
  param([string]$Path)

  if (-not (Test-Path -LiteralPath $Path)) {
    Write-Error "Dotenv file not found: $Path"
  }

  Get-Content -LiteralPath $Path | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) {
      return
    }

    $eq = $line.IndexOf("=")
    if ($eq -lt 1) {
      return
    }

    $key = $line.Substring(0, $eq).Trim()
    $value = $line.Substring($eq + 1).Trim()

    # Strip optional quotes
    if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
      $value = $value.Substring(1, $value.Length - 2)
    }

    if ($key) {
      Set-Item -Path ("Env:{0}" -f $key) -Value $value
    }
  }
}

Import-DotEnvFile -Path $EnvFile

& $Command @Arguments
exit $LASTEXITCODE
