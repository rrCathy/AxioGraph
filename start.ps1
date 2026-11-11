# AxioGraph development launcher
#
#   .\start.ps1                  backend (background job) + frontend
#   .\start.ps1 -FrontendOnly    frontend only; use when running uvicorn
#                                with --reload in a separate terminal
#
# Backend hot reload, in a separate terminal:
#   cd backend; python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
#   .\start.ps1 -FrontendOnly
#
# Requires: Python 3.12 on PATH (backend/.env) and npm install in frontend/.

param([switch]$FrontendOnly)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backendDir = Join-Path $root 'backend'
$frontendDir = Join-Path $root 'frontend'
$healthUrl = 'http://127.0.0.1:8000/api/health'
$backendJob = $null

function Test-BackendHealth {
    $body = & curl.exe -s --noproxy '*' --max-time 2 $healthUrl 2>$null
    return ($LASTEXITCODE -eq 0 -and $body -match '"status"\s*:\s*"ok"')
}

try {
    if (-not $FrontendOnly) {
        if (Test-BackendHealth) {
            Write-Host 'Backend already healthy on 8000 - reusing it.' -ForegroundColor Green
            Write-Host '  (restart that process to pick up backend code changes)' -ForegroundColor DarkGray
        }
        else {
            Write-Host 'Starting backend on http://127.0.0.1:8000 ...' -ForegroundColor Cyan
            $backendJob = Start-Job -ScriptBlock {
                param($dir)
                Set-Location $dir
                python -m uvicorn main:app --host 127.0.0.1 --port 8000
            } -ArgumentList $backendDir

            $ready = $false
            for ($i = 0; $i -lt 40; $i++) {
                if (Test-BackendHealth) { $ready = $true; break }
                if ($backendJob.State -eq 'Failed') { break }
                Start-Sleep -Milliseconds 500
            }
            if (-not $ready) {
                Write-Host 'Backend did not become healthy. Job output:' -ForegroundColor Red
                Receive-Job $backendJob -ErrorAction SilentlyContinue | Out-Host
                throw 'Backend failed to start; see output above.'
            }
            Write-Host 'Backend healthy.' -ForegroundColor Green
        }
    }
    else {
        if (Test-BackendHealth) {
            Write-Host 'Using existing backend at 127.0.0.1:8000' -ForegroundColor Green
        }
        else {
            Write-Host 'WARNING: no backend on 8000 - /api calls will fail.' -ForegroundColor Yellow
        }
    }

    $vite = Join-Path $frontendDir 'node_modules\.bin\vite.cmd'
    if (-not (Test-Path $vite)) {
        throw "vite.cmd not found at $vite - run npm install in frontend/"
    }
    Write-Host 'Starting frontend on http://127.0.0.1:5173 ...' -ForegroundColor Cyan
    Set-Location $frontendDir
    & $vite --host 127.0.0.1
}
finally {
    Set-Location $root
    if ($null -ne $backendJob) {
        Write-Host 'Stopping backend...' -ForegroundColor Yellow
        Stop-Job $backendJob -ErrorAction SilentlyContinue
        Remove-Job $backendJob -Force -ErrorAction SilentlyContinue
    }
}
