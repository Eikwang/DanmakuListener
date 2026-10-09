@echo off
title danmaku-serve (danmaku listener)
cd /d D:\AI\DanmakuListener
:loop
echo [runner] Service starting %time%
python -m danmaku_listener serve --web >> "%~dp0svc-console.log" 2>&1
echo [runner] Service exited rc=%errorlevel% %time% —— Restarting in 2 seconds
timeout /t 2 /nobreak >nul
goto loop
