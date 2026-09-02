@echo off
rem 全平台数据统计器（双击启动，浏览器访问 http://127.0.0.1:8766）
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
  start "" python app.py
) else (
  start "" "C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe" app.py
)
timeout /t 2 >nul
start "" http://127.0.0.1:8766
