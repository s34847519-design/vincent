@echo off
chcp 65001 >nul
title 文森特
cd /d "%~dp0"

rem 跑掛了就自己爬起來。想收工就直接關掉這個視窗。
:loop
echo.
echo [%date% %time%] 啟動中...
python3.14 run.py
echo.
echo [%date% %time%] 程式結束（離開碼 %errorlevel%），10 秒後重開。
echo 不想重開就現在關掉這個視窗。
timeout /t 10 >nul
goto loop
