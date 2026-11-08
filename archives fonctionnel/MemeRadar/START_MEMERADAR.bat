@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ===============================================
echo MemeRadar v6.7 - Solana Scanner (lecture seule)
echo ===============================================
py -3.13 --version >nul 2>nul
if not errorlevel 1 goto python313
where py >nul 2>nul
if not errorlevel 1 goto python3
goto pythonfallback

:python313
py -3.13 main.py --interval 20
if %errorlevel%==75 goto python313
goto end

:python3
py -3 main.py --interval 20
if %errorlevel%==75 goto python3
goto end

:pythonfallback
python main.py --interval 20
if %errorlevel%==75 goto pythonfallback

:end
echo.
echo MemeRadar arrete.
pause
