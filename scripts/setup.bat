@echo off
setlocal
rem Setup on Windows: Python 3.12 virtual environment + Node packages.
rem Run it once, and again after pulling a version with new packages.
rem Close running project windows first: Windows locks files that are in use.
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

node -e "const [a,b]=process.versions.node.split('.').map(Number);process.exit(a>22||(a===22&&b>=12)||(a===20&&b>=19)?0:1)" >nul 2>&1
if errorlevel 1 (
  echo Note: Node.js 22 LTS is recommended ^(you have an older version^). Get it from https://nodejs.org
)
pushd "%FRONTEND%"
rem Remove the old build cache so styles are rebuilt with the new packages.
if exist ".next" rmdir /s /q ".next"
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
