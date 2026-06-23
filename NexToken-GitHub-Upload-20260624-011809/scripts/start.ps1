param([switch]$NoBrowser)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".env")) {
    $bytes = New-Object byte[] 48
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $rng.Dispose()
    $secret = [Convert]::ToBase64String($bytes)
    $password = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object {[char]$_})
    $envContent = @"
APP_PORT=3100
TZ=Asia/Taipei
NEXTOKEN_RUNTIME=local
DATABASE_URL=sqlite:///./data/nextoken.db
REDIS_URL=
REDIS_REQUIRED=false
ADMIN_USERNAME=admin
ADMIN_PASSWORD=$password
APP_SECRET=$secret
ALLOWED_ORIGINS=http://127.0.0.1:3100,http://localhost:3100
GOOGLE_CLIENT_ID=
"@
    [IO.File]::WriteAllText((Join-Path $Root ".env"), $envContent, (New-Object Text.UTF8Encoding($false)))
    Write-Host "Created local administrator credentials." -ForegroundColor Green
}

function Add-EnvDefault([string]$Name, [string]$Value) {
    $present = Get-Content ".env" | Where-Object { $_ -like "${Name}=*" } | Select-Object -First 1
    if (-not $present) {
        Add-Content -Path ".env" -Value "${Name}=${Value}" -Encoding UTF8
    }
}

function Get-EnvValue([string]$Name) {
    $line = Get-Content ".env" | Where-Object { $_ -like "${Name}=*" } | Select-Object -First 1
    if (-not $line) { return "" }
    return ([string]$line).Substring($Name.Length + 1).Trim()
}

$passwordChars = (48..57) + (65..90) + (97..122)
$postgresPassword = -join ($passwordChars | Get-Random -Count 32 | ForEach-Object {[char]$_})
$redisPassword = -join ($passwordChars | Get-Random -Count 32 | ForEach-Object {[char]$_})
Add-EnvDefault "DATABASE_URL" "sqlite:///./data/nextoken.db"
Add-EnvDefault "NEXTOKEN_RUNTIME" "local"
Add-EnvDefault "REDIS_URL" ""
Add-EnvDefault "REDIS_REQUIRED" "false"
Add-EnvDefault "GOOGLE_CLIENT_ID" ""
Add-EnvDefault "POSTGRES_DB" "nextoken"
Add-EnvDefault "POSTGRES_USER" "nextoken"
Add-EnvDefault "POSTGRES_PASSWORD" $postgresPassword
Add-EnvDefault "REDIS_PASSWORD" $redisPassword

$adminUser = Get-EnvValue "ADMIN_USERNAME"
$adminPass = Get-EnvValue "ADMIN_PASSWORD"
$appSecret = Get-EnvValue "APP_SECRET"
$allowedOrigins = Get-EnvValue "ALLOWED_ORIGINS"
$runtime = (Get-EnvValue "NEXTOKEN_RUNTIME").ToLowerInvariant()
$databaseUrl = Get-EnvValue "DATABASE_URL"
$redisUrl = Get-EnvValue "REDIS_URL"
$redisRequired = Get-EnvValue "REDIS_REQUIRED"
$googleClientId = Get-EnvValue "GOOGLE_CLIENT_ID"

$dockerReady = $false
try {
    docker info *> $null
    $dockerReady = $true
} catch {}

if ($runtime -eq "docker" -and $dockerReady) {
    docker compose up -d --build
} elseif ($runtime -eq "docker") {
    Write-Host "NEXTOKEN_RUNTIME is docker, but Docker Desktop is unavailable." -ForegroundColor Red
    exit 1
} elseif (Test-Path ".venv\Scripts\python.exe") {
    New-Item -ItemType Directory -Force "data" | Out-Null
    $existing = Get-NetTCPConnection -LocalPort 3100 -State Listen -ErrorAction SilentlyContinue
    if (-not $existing) {
        $env:DATABASE_URL = if ($databaseUrl) { $databaseUrl } else { "sqlite:///./data/nextoken.db" }
        $env:REDIS_URL = $redisUrl
        $env:REDIS_REQUIRED = if ($redisRequired) { $redisRequired } else { "false" }
        $env:APP_SECRET = $appSecret
        $env:ADMIN_USERNAME = $adminUser
        $env:ADMIN_PASSWORD = $adminPass
        $env:ALLOWED_ORIGINS = $allowedOrigins
        $env:GOOGLE_CLIENT_ID = $googleClientId
        & ".\.venv\Scripts\python.exe" "scripts\migrate.py"
        if ($LASTEXITCODE -ne 0) { throw "Database migration failed." }
        $process = Start-Process -FilePath ".\.venv\Scripts\python.exe" `
            -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "3100" `
            -WorkingDirectory $Root -WindowStyle Hidden `
            -RedirectStandardOutput "data\local.out.log" -RedirectStandardError "data\local.err.log" -PassThru
        Set-Content "data\local.pid" $process.Id
    }
    Write-Host "Docker is not running; using the local NexToken runtime." -ForegroundColor Yellow
} else {
    Write-Host "Docker Desktop is not running and the local runtime is unavailable." -ForegroundColor Red
    Write-Host "Install or start Docker Desktop, then run Start-NexToken.bat again."
    exit 1
}

Write-Host "Waiting for NexToken Local..."
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $health = Invoke-RestMethod "http://127.0.0.1:3100/health" -TimeoutSec 2
        if ($health.status -eq "ok") { $ready = $true; break }
    } catch {}
    Start-Sleep -Seconds 2
}

if (-not $ready) {
    Write-Host "Startup timed out. Run: docker compose logs app" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "NexToken Local is running." -ForegroundColor Green
Write-Host "Shop:     http://127.0.0.1:3100/"
Write-Host "Admin:    http://127.0.0.1:3100/admin"
Write-Host "Customer: http://127.0.0.1:3100/customer"
Write-Host "API:      http://127.0.0.1:3100/v1"
Write-Host "Admin user: $adminUser"
Write-Host "Admin password: $adminPass"

if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:3100/admin"
}
