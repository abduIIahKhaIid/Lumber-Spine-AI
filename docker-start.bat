@echo off
setlocal
title Lumber Spine AI - Docker
rem Builds (first time) and starts redis, api, worker and web with Docker Compose.
cd /d "%~dp0"

docker version >nul 2>&1
if errorlevel 1 (
  echo Docker is not running. Install Docker Desktop, start it, wait until it says
  echo "Engine running", then run this file again.
  pause & exit /b 1
)
docker compose version >nul 2>&1
if errorlevel 1 (
  echo Docker Compose v2 is missing. Update Docker Desktop.
  pause & exit /b 1
)

if not exist "backend\.env" (
  copy "backend\.env.example" "backend\.env" >nul
  echo Created backend\.env from the template. Add your API keys there for the assistant.
)

set "MISSING="
for %%M in (stage1_scs.pt stage2_scs.pt severity_model_full_scs.pth best_scs.pt stage1_nfn.pt stage2_nfn.pt severity_model_full_nfn.pth best_nfn.pt stage1_ss.pt stage2_ss.pt severity_model_full_ss.pth best_ss.pt) do (
  if not exist "backend\model\%%M" set "MISSING=1" & echo Missing model file: backend\model\%%M
)
if defined MISSING echo Analyses for the missing models will fail until the files are added.

echo.
echo Building and starting containers. The first build downloads PyTorch and can take
echo 10-20 minutes; later starts take seconds.
echo.
docker compose up -d --build
if errorlevel 1 (
  echo.
  echo Docker Compose failed. Read the messages above.
  pause & exit /b 1
)

echo.
echo Waiting for the API...
for /l %%i in (1,1,60) do (
  curl -fs http://localhost:8000/health >nul 2>&1 && goto :api_ready
  timeout /t 2 /nobreak >nul
)
echo The API did not answer. Check: docker compose logs api
pause & exit /b 1

:api_ready
echo Waiting for the analysis worker to load the models...
for /l %%i in (1,1,90) do (
  curl -fs http://localhost:8000/ready >nul 2>&1 && goto :ready
  timeout /t 2 /nobreak >nul
)
echo The worker is still starting. Analyses will queue until it is ready.
echo Follow it with: docker compose logs -f worker

:ready
docker compose ps
echo.
echo SpineScope is running at http://localhost:3000
start "" http://localhost:3000
echo Stop it with docker-stop.bat. Saved cases and chats are kept between restarts.
pause
