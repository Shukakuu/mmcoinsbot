@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Mode DEMO : toutes les monnaies sont fictives.
py -3.13 --version >nul 2>nul
if not errorlevel 1 goto python313
where py >nul 2>nul
if not errorlevel 1 goto python3
python main.py --demo
goto end
:python313
py -3.13 main.py --demo
goto end
:python3
py -3 main.py --demo
:end
pause
