@echo off
cd /d "%~dp0"
docker compose down
echo Stopped. Saved cases and chats are kept (docker compose down -v deletes them).
pause
