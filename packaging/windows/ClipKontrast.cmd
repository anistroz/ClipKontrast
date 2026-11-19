@echo off
rem ClipKontrast, the Windows app. Started from the desktop and Start menu shortcuts made by the installer.
rem Everything is inside this folder: python (with all libraries), ffmpeg, app (ClipKontrast's code) and data
rem (videos, clips, settings and keys). An update replaces only "app": it is unpacked as "app.new" while
rem ClipKontrast runs, which then stops with code 75, and the new code is swapped in here before it starts again.
title ClipKontrast
cd /d "%~dp0"
set "CLIPKONTRAST_INSTALLED=1"
set "CLIPKONTRAST_INSTALL_DIR=%~dp0."
set "CLIPKONTRAST_DEFAULT_DATA=%~dp0data"
set "CLIPKONTRAST_STORAGE_FILE=%~dp0storage.json"
set "CLIPKONTRAST_AUTO_RELOAD=0"
set "PYTHONUTF8=1"
set "PYTHONWARNINGS=ignore::DeprecationWarning"
set "PATH=%~dp0ffmpeg\bin;%~dp0python;%~dp0python\Scripts;%PATH%"

:start
if exist "%~dp0app.new\studio\server.py" (
    if exist "%~dp0app.old" rmdir /s /q "%~dp0app.old"
    move "%~dp0app" "%~dp0app.old" >nul
    move "%~dp0app.new" "%~dp0app" >nul
    echo   ClipKontrast was updated.
)
rem If the swap could not finish (a file was open somewhere), the old code goes back where it was.
if not exist "%~dp0app\studio\server.py" if exist "%~dp0app.old\studio\server.py" (
    if exist "%~dp0app" rmdir /s /q "%~dp0app"
    move "%~dp0app.old" "%~dp0app" >nul
)
echo.
echo   Starting ClipKontrast. Keep this window open while you use it: closing it stops ClipKontrast.
echo   The first start downloads the speech model (about 480 MB, once).
echo.
"%~dp0python\python.exe" -m studio.server
set "CODE=%ERRORLEVEL%"
if "%CODE%"=="75" (
    set "CLIPKONTRAST_OPEN_BROWSER=0"
    goto start
)
if "%CODE%"=="76" (
    echo   Installing the new version. ClipKontrast starts again when it is done.
    start "" "%~dp0update\ClipKontrast-Setup.exe" /SILENT /SUPPRESSMSGBOXES /NORESTART
    exit /b 0
)
echo.
echo   ClipKontrast has stopped. Press any key to close this window.
pause >nul
