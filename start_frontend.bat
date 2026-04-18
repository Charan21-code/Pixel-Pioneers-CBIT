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
echo Frontend starting on http://192.168.137.97:3000
timeout /t 3 /nobreak
start http://192.168.137.97:3000
