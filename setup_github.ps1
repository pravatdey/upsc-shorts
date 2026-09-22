# =============================================================================
#  One-shot GitHub setup for the UPSC Shorts pipeline.
#
#  Run it as many times as you like - it only does what is still missing.
#  Run it again after you fill in .env, and it will set the secrets it skipped.
#
#      powershell -ExecutionPolicy Bypass -File setup_github.ps1
# =============================================================================

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$RepoName = "upsc-shorts"

function Step($text)  { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }
function Good($text)  { Write-Host "    OK   $text" -ForegroundColor Green }
function Warn($text)  { Write-Host "    WARN $text" -ForegroundColor Yellow }
function Bad($text)   { Write-Host "    FAIL $text" -ForegroundColor Red }

Write-Host ""
Write-Host "  UPSC Shorts - GitHub setup" -ForegroundColor White
Write-Host "  ----------------------------------------"

# ---------------------------------------------------------------- find gh ----
Step "Locating GitHub CLI"
$gh = $null
$cmd = Get-Command gh -ErrorAction SilentlyContinue
if ($cmd) {
    $gh = $cmd.Source
} elseif (Test-Path "C:\Program Files\GitHub CLI\gh.exe") {
    $gh = "C:\Program Files\GitHub CLI\gh.exe"
}

if (-not $gh) {
    Bad "GitHub CLI not found."
    Write-Host "         Install it with:  winget install --id GitHub.cli" -ForegroundColor Gray
    exit 1
}
Good $gh

# ------------------------------------------------------------------ login ----
Step "Checking GitHub login"
& $gh auth status 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Warn "Not logged in. Starting login now."
    Write-Host ""
    Write-Host "    Answer the prompts like this:" -ForegroundColor Gray
    Write-Host "      Account            -> GitHub.com"              -ForegroundColor Gray
    Write-Host "      Protocol           -> HTTPS"                   -ForegroundColor Gray
    Write-Host "      Authenticate Git?  -> Yes"                     -ForegroundColor Gray
    Write-Host "      How to authenticate-> Login with a web browser" -ForegroundColor Gray
    Write-Host "      Then copy the code shown and press Enter."     -ForegroundColor Gray
    Write-Host ""

    & $gh auth login
    if ($LASTEXITCODE -ne 0) {
        Bad "Login did not complete. Run this script again when ready."
        exit 1
    }
}

$user = (& $gh api user --jq .login) 2>$null
if (-not $user) {
    Bad "Logged in, but could not read your username."
    exit 1
}
Good "Signed in as $user"

# ------------------------------------------------------------------- repo ----
Step "Preparing repository $user/$RepoName"

& $gh repo view "$user/$RepoName" 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Good "Repository already exists"
} else {
    & $gh repo create $RepoName --public --description "Automated daily UPSC/civil services YouTube Shorts" --disable-wiki
    if ($LASTEXITCODE -ne 0) {
        Bad "Could not create the repository"
        exit 1
    }
    Good "Created public repository"
}

# ------------------------------------------------------------------- push ----
Step "Pushing code"

# Safety net: never push if a secret file somehow became tracked.
$tracked = git ls-files
foreach ($leak in @(".env", "config/client_secrets.json", "config/youtube_token.json")) {
    if ($tracked -contains $leak) {
        Bad "$leak is tracked by git. Aborting so your credentials are not published."
        Write-Host "         Fix with:  git rm --cached $leak" -ForegroundColor Gray
        exit 1
    }
}
Good "No secret files are tracked"

$remoteUrl = "https://github.com/$user/$RepoName.git"
if (git remote) {
    git remote set-url origin $remoteUrl
} else {
    git remote add origin $remoteUrl
}

git push -u origin main
if ($LASTEXITCODE -ne 0) {
    Bad "Push failed. See the git output above."
    exit 1
}
Good "Pushed to $remoteUrl"

# ---------------------------------------------------------------- secrets ----
Step "Setting repository secrets"

# Reads a KEY=value line from .env without ever printing the value.
function Get-EnvValue($name) {
    if (-not (Test-Path ".env")) { return "" }
    foreach ($line in (Get-Content ".env" -Encoding UTF8)) {
        if ($line -match "^\s*$name\s*=\s*(.+)\s*$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return ""
}

$missing = @()

foreach ($name in @("GROQ_API_KEY", "GEMINI_API_KEY")) {
    $value = Get-EnvValue $name
    if ([string]::IsNullOrWhiteSpace($value)) {
        Warn "$name is empty in .env - skipped"
        $missing += $name
    } else {
        $value | & $gh secret set $name --repo "$user/$RepoName"
        if ($LASTEXITCODE -eq 0) {
            Good "$name set ($($value.Length) chars)"
        } else {
            Bad "$name could not be set"
            $missing += $name
        }
    }
}

if (Test-Path "config/youtube_token.json") {
    Get-Content "config/youtube_token.json" -Raw -Encoding UTF8 | & $gh secret set YOUTUBE_TOKEN --repo "$user/$RepoName"
    if ($LASTEXITCODE -eq 0) {
        Good "YOUTUBE_TOKEN set"
    } else {
        Bad "YOUTUBE_TOKEN could not be set"
        $missing += "YOUTUBE_TOKEN"
    }
} else {
    Warn "config/youtube_token.json not found - YOUTUBE_TOKEN skipped"
    $missing += "YOUTUBE_TOKEN"
}

# ----------------------------------------------------------------- finish ----
Write-Host ""
Write-Host "  ----------------------------------------" -ForegroundColor White
Write-Host "  Repository: https://github.com/$user/$RepoName" -ForegroundColor White
Write-Host "  Actions   : https://github.com/$user/$RepoName/actions" -ForegroundColor White

if ($missing.Count -eq 0) {
    Write-Host ""
    Write-Host "  Everything is set. Do a private test run first:" -ForegroundColor Green
    Write-Host "    Actions tab -> Daily UPSC Shorts -> Run workflow" -ForegroundColor Gray
    Write-Host "    Set test_mode to 'true' so the videos upload as private." -ForegroundColor Gray
} else {
    Write-Host ""
    Write-Host "  Still missing: $($missing -join ', ')" -ForegroundColor Yellow
    if ($missing -contains "GROQ_API_KEY" -or $missing -contains "GEMINI_API_KEY") {
        Write-Host "    - Paste the keys into .env and SAVE, then run this script again." -ForegroundColor Gray
    }
    if ($missing -contains "YOUTUBE_TOKEN") {
        Write-Host "    - Save the OAuth JSON as config\client_secrets.json," -ForegroundColor Gray
        Write-Host "      run: python authorize_youtube.py" -ForegroundColor Gray
        Write-Host "      then run this script again." -ForegroundColor Gray
    }
    Write-Host ""
    Write-Host "  Re-running this script is safe - it only fills in what is missing." -ForegroundColor Gray
}
Write-Host ""
