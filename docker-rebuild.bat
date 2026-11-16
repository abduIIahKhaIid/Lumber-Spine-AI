@echo off
rem Rebuild the images from your local code (use after changing code), then start.
call "%~dp0docker-start.bat" build
