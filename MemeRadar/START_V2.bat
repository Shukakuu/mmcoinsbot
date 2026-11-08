@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo MemeRadar V2 - Veille uniquement, achats manuels
call START_MEMERADAR.bat
