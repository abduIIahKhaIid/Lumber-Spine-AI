@echo off
setlocal
rem One-time setup on Windows: Python 3.12 virtual environment + Node packages.
set "ROOT=%~dp0.."
set "BACKEND=%ROOT%\backend"
set "FRONTEND=%ROOT%\frontend"

where py >nul 2>&1 && (set "PYLAUNCH=py -3.12") || (set "PYLAUNCH=python")
if not exist "%BACKEND%\.venv\Scripts\python.exe" (
  echo Creating backend\.venv ...
  %PYLAUNCH% -m venv "%BACKEND%\.venv" || goto :fail
)
"%BACKEND%\.venv\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
pushd "%BACKEND%"
".venv\Scripts\python.exe" -m pip install -e ".[ml,dev]" || (popd & goto :fail)
popd
if not exist "%BACKEND%\.env" copy "%BACKEND%\.env.example" "%BACKEND%\.env" >nul

pushd "%FRONTEND%"
call npm.cmd ci --no-audit --no-fund || (popd & goto :fail)
popd
echo.
echo Setup complete. Put the model checkpoints in backend\model, add API keys to backend\.env,
echo then run run-project.bat.
pause
exit /b 0

:fail
echo Setup failed. Read the messages above.
pause
exit /b 1
