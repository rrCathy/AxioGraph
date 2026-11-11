# AxioGraph MVP — Start Script

# Start backend
Write-Host "Starting backend on http://127.0.0.1:8000 ..." -ForegroundColor Cyan
$backendJob = Start-Job -ScriptBlock {
    Set-Location "C:\newproject\AxioGraph\backend"
    python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
}

# Start frontend
Write-Host "Starting frontend on http://localhost:5173 ..." -ForegroundColor Cyan
Set-Location "C:\newproject\AxioGraph\frontend"
npx vite --host 127.0.0.1

# Cleanup on exit
Write-Host "Shutting down backend..." -ForegroundColor Yellow
Stop-Job $backendJob
Remove-Job $backendJob
