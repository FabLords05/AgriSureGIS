@echo off
rem ---------------------------------------------------------------------------
rem AgriSureGIS - one-click start for the backend (FastAPI) and GeoServer.
rem Each server opens in its own window; close a window (or Ctrl+C in it) to
rem stop that server. A server already listening on its port is skipped, so
rem double-clicking this twice doesn't start duplicates.
rem
rem Machine-specific paths -- edit these if your install differs.
rem ---------------------------------------------------------------------------
setlocal

set "ROOT=%~dp0"
set "BACKEND_DIR=%ROOT%backend"
set "BACKEND_PYTHON=%BACKEND_DIR%\.venv\Scripts\python.exe"
set "GEOSERVER_HOME=C:\geoserver"
if not defined JAVA_HOME set "JAVA_HOME=C:\Program Files\Eclipse Adoptium\jdk-17.0.20.8-hotspot"

rem --- GeoServer (port 8080) -------------------------------------------------
netstat -ano | findstr /R /C:":8080 .*LISTENING" >nul
if not errorlevel 1 (
    echo [GeoServer] Already running on port 8080 - skipped.
) else if not exist "%GEOSERVER_HOME%\bin\startup.bat" (
    echo [GeoServer] Not found at %GEOSERVER_HOME% - edit GEOSERVER_HOME in this file.
) else if not exist "%JAVA_HOME%\bin\java.exe" (
    echo [GeoServer] Java not found at %JAVA_HOME% - edit JAVA_HOME in this file.
) else (
    echo [GeoServer] Starting...  http://localhost:8080/geoserver/web
    start "AgriSureGIS - GeoServer" /D "%GEOSERVER_HOME%\bin" cmd /k startup.bat
)

rem --- Backend (port 8000) ---------------------------------------------------
netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul
if not errorlevel 1 (
    echo [Backend]   Already running on port 8000 - skipped.
) else if not exist "%BACKEND_PYTHON%" (
    echo [Backend]   venv not found at %BACKEND_PYTHON% - create it first.
) else (
    echo [Backend]   Starting...  http://localhost:8000/docs
    rem --host 0.0.0.0 is required for Tailscale peers (see .claude/LOCAL_SERVER_SETUP.md).
    start "AgriSureGIS - Backend" /D "%BACKEND_DIR%" cmd /k ""%BACKEND_PYTHON%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
)

echo.
echo Done. This window closes in 5 seconds.
timeout /t 5 >nul
endlocal
