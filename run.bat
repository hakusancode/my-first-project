@echo off
REM 기업 재무분석 도구 — Windows 실행 런처
REM 더블클릭하면 가상환경 생성 + 패키지 설치 + 실행까지 자동으로 진행됩니다.
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py") || (set "PY=python")

if not exist ".venv\Scripts\python.exe" (
    echo [설정] 가상환경 생성 및 패키지 설치 중... 처음 한 번만 걸립니다.
    %PY% -m venv .venv
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip
    pip install -r requirements.txt
) else (
    call ".venv\Scripts\activate.bat"
)

echo [실행] 기업 재무분석 도구를 시작합니다...
python dart_gui.py
if errorlevel 1 pause
