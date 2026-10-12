@echo off
rem ---------------------------------------------------------------------------
rem AgriSureGIS - one-click start for the backend (FastAPI) and GeoServer.
rem Each server opens in its own window; close a window (or Ctrl+C in it) to
rem stop that server. A server already listening on its port is skipped, so
rem double-clicking this twice doesn't start duplicates.
rem
rem   start-servers.bat        development: backend with --reload
rem   start-servers.bat prod   public (Tailscale Funnel) deployment: backend
rem                            without --reload
rem
rem Both modes also start Caddy on 127.0.0.1:8090 serving frontend\dist -- the
rem last `npm run build`, not live source (use Vite on :5173 for that). See
rem deploy\Caddyfile and .claude\LOCAL_SERVER_SETUP.md section 9.
rem
rem Machine-specific paths -- edit these if your install differs.
rem ---------------------------------------------------------------------------
setlocal

set "ROOT=%~dp0"
set "BACKEND_DIR=%ROOT%backend"
set "BACKEND_PYTHON=%BACKEND_DIR%\.venv\Scripts\python.exe"
set "GEOSERVER_HOME=C:\geoserver"
if not defined JAVA_HOME set "JAVA_HOME=C:\Program Files\Eclipse Adoptium\jdk-17.0.20.8-hotspot"

set "MODE=dev"
if /I "%~1"=="prod" set "MODE=prod"
set "RELOAD_FLAG=--reload"
if "%MODE%"=="prod" set "RELOAD_FLAG="
echo Mode: %MODE%
echo.

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
    start "AgriSureGIS - Backend" /D "%BACKEND_DIR%" cmd /k ""%BACKEND_PYTHON%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 %RELOAD_FLAG%"
)

rem --- Caddy (port 8090) -----------------------------------------------------
netstat -ano | findstr /R /C:":8090 .*LISTENING" >nul
if not errorlevel 1 (
    echo [Caddy]     Already running on port 8090 - skipped.
    goto :done
)
rem Terminals opened before `winget install CaddyServer.Caddy` (e.g. VS Code's,
rem until VS Code restarts) don't see its PATH entry yet -- fall back to winget's folder.
set "CADDY=caddy"
where caddy >nul 2>nul
if not errorlevel 1 goto :caddy_found
set "CADDY=%LOCALAPPDATA%\Microsoft\WinGet\Packages\CaddyServer.Caddy_Microsoft.Winget.Source_8wekyb3d8bbwe\caddy.exe"
if exist "%CADDY%" goto :caddy_found
echo [Caddy]     caddy not found - install it first (winget install CaddyServer.Caddy).
goto :done

:caddy_found
if not exist "%ROOT%frontend\dist\index.html" (
    echo [Caddy]     frontend\dist not found - run npm run build in frontend first.
) else (
    echo [Caddy]     Starting...  http://127.0.0.1:8090  ^(public through Tailscale Funnel^)
    start "AgriSureGIS - Caddy" /D "%ROOT%" cmd /k ""%CADDY%" run --config deploy\Caddyfile"
)

:done

echo.
echo Done. This window closes in 5 seconds.
timeout /t 5 >nul
endlocal
