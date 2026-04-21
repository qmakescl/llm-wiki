@echo off
REM llm-wiki 원클릭 실행 스크립트 (Windows)
REM 사용법: 이 파일을 더블클릭하거나 명령 프롬프트에서 실행

title llm-wiki

echo ================================================
echo   llm-wiki 시작
echo ================================================

REM 현재 스크립트 위치로 이동
cd /d "%~dp0"

REM Python 확인
where python >nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되지 않았습니다.
    echo        https://www.python.org 에서 Python 3.11 이상을 설치하세요.
    echo        설치 시 "Add Python to PATH" 옵션을 반드시 체크하세요.
    pause
    exit /b 1
)

REM 가상환경 생성 (최초 1회)
if not exist ".venv" (
    echo [설정] 첫 실행입니다. 가상환경을 설정합니다 약 1~2분 소요...
    python -m venv .venv
    echo [설정] 패키지 설치 중...
    .venv\Scripts\pip install --upgrade pip -q
    .venv\Scripts\pip install -e ".[web]" -q
    echo [설정] 완료^^!
)

REM 서버 시작 및 브라우저 열기
echo [시작] 브라우저에서 http://localhost:8000 이 열립니다...
start "" .venv\Scripts\python -m wiki_web
timeout /t 2 /nobreak > nul
start http://localhost:8000
