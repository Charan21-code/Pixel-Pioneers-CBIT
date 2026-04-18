@echo off
echo ============================================
echo  OPS//CORE - Starting FastAPI Backend
echo ============================================
cd /d "%~dp0.."
call myenv\Scripts\activate 2>nul || python -m venv myenv && call myenv\Scripts\activate
pip install -q fastapi uvicorn[standard]
cd backend
start "OPS-CORE Backend" cmd /k "python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000"
echo Backend starting on http://192.168.137.97:8000
echo API docs available at http://192.168.137.97:8000/docs
