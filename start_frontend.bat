@echo off
echo ============================================
echo  OPS//CORE - Starting React Frontend
echo ============================================
cd /d "%~dp0frontend"
if not exist node_modules (
    echo Installing dependencies...
    call npm install
)
start "OPS-CORE Frontend" cmd /k "npm run dev"
echo Frontend starting on http://localhost:3000
timeout /t 3 /nobreak
start http://localhost:3000
