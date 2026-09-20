@echo off
cd /d "%~dp0"
title 군부 겹판 분할 헬멧 낙하 충격 시뮬레이터

REM 처음 실행하면 가상환경을 만들고 패키지를 설치한다 (1~3분). 다음부터는 바로 켜진다.
if not exist ".venv\Scripts\streamlit.exe" (
    echo [1/2] 처음 실행입니다. 파이썬 환경을 준비합니다. 1~3분 걸립니다...
    where py >nul 2>&1
    if errorlevel 1 ( python -m venv .venv ) else ( py -3 -m venv .venv )
    if errorlevel 1 (
        echo.
        echo [오류] 파이썬을 찾지 못했습니다.
        echo        https://www.python.org/downloads/ 에서 설치할 때
        echo        "Add python.exe to PATH" 를 체크한 뒤 다시 실행하세요.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet
    if errorlevel 1 (
        echo.
        echo [오류] 패키지 설치에 실패했습니다. 인터넷 연결을 확인하고 다시 실행하세요.
        pause
        exit /b 1
    )
)

echo [2/2] 앱을 켭니다. 브라우저가 자동으로 열립니다.
echo        주소: http://localhost:8501      종료: 이 창에서 Ctrl+C
echo.
".venv\Scripts\streamlit.exe" run app.py
pause
