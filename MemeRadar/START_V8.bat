@echo off
chcp 65001 >NUL
cd /d "%~dp0"
echo MemeRadar v8.1 - lecture seule, J7 et lancements Solana
powershell -NoProfile -File "%~dp0START_J7.ps1"
