@echo off
setlocal
title Lumber Spine AI
rem Starts the API, a Celery worker (when Redis is running) and the web app,
rem each in its own window. Run scripts\setup.bat once before the first start.

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
set "PY=%BACKEND%\.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo Backend environment not found. Run scripts\setup.bat first.
  pause & exit /b 1
)
rem Packages change between versions: stop early instead of starting a broken app.
"%PY%" -c "import celery, redis, fastapi, torch, timm, ultralytics, pydicom" >nul 2>&1
if errorlevel 1 (
  echo Backend packages are missing or out of date.
  echo Close any running project windows, then run scripts\setup.bat.
  pause & exit /b 1
)
if not exist "%FRONTEND%\node_modules\recharts\package.json" goto :frontend_outdated
if not exist "%FRONTEND%\node_modules\@fontsource-variable\atkinson-hyperlegible-next\package.json" goto :frontend_outdated

rem Redis is optional: without it the API runs analyses in-process.
"%PY%" -c "import redis,sys; sys.exit(0 if redis.Redis(socket_connect_timeout=1).ping() else 1)" >nul 2>&1
if errorlevel 1 (
  echo Redis is not running on localhost:6379 - analyses will run inside the API process.
  echo Start Redis ^(Docker: docker run -d -p 6379:6379 redis:7-alpine^) to use the Celery worker.
) else (
  echo Redis found - starting the Celery worker.
  start "Lumber Spine AI - worker" /D "%BACKEND%" "%ComSpec%" /k ""%PY%" -m celery -A app.worker.celery_app worker --loglevel=info --pool=solo"
)

start "Lumber Spine AI - API (8000)" /D "%BACKEND%" "%ComSpec%" /k ""%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
start "Lumber Spine AI - web (3000)" /D "%FRONTEND%" "%ComSpec%" /k "npm.cmd run dev -- --hostname 127.0.0.1 --port 3000"

echo.
echo Open http://localhost:3000 once the windows report they are ready.
echo Close the windows to stop the project.
pause
exit /b 0

:frontend_outdated
echo Frontend packages are missing or out of date.
echo Close any running project windows, then run scripts\setup.bat.
pause
exit /b 1
