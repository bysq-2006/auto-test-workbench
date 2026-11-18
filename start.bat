@echo off
cd /d "%~dp0"
title auto-test-workbench  :8000

set "PY=C:\Users\19045\anaconda3\envs\teacher\python.exe"

echo ==========================================
echo   工作台  http://127.0.0.1:8000
echo   这个窗口就是服务本体，关掉窗口即停服
echo   出错会停在这里，按任意键才退出
echo ==========================================
echo.

rem 端口还被上一个实例占着时先结束它，否则 uvicorn 直接退出、窗口一闪而过
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
  echo [提示] 端口 8000 已被进程 %%p 占用，先结束它再启动...
  taskkill /PID %%p /T /F >nul 2>&1
)

start "" %COMSPEC% /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8000"

"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

echo.
echo ==========================================
echo   服务已退出，退出码 %errorlevel%
echo ==========================================
pause
