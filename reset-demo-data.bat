@echo off
rem ---------------------------------------------------------------------------
rem AgriSureGIS - one-click reset for the ingestion demo.
rem
rem Splits the client's Typhoon Tino CSV + GeoPackage 50/50 (per farmer) into
rem   USTP CAPSTONE\DEMO\already_ingested\   pre-loaded by this script
rem   USTP CAPSTONE\DEMO\to_ingest\          upload live in the UI (CSV, then .gpkg)
rem then clears all farmers/farms/insurance records/assessments and ingests the
rem already_ingested half. Users, boundaries, matrices, typhoons and bulletins
rem are kept. Asks you to type YES before touching the database.
rem
rem   reset-demo-data.bat              split + reset + pre-ingest
rem   reset-demo-data.bat --split-only only regenerate the DEMO files
rem
rem See backend\prepare_ingestion_demo.py for details.
rem ---------------------------------------------------------------------------
setlocal

set "ROOT=%~dp0"
set "BACKEND_DIR=%ROOT%backend"
set "BACKEND_PYTHON=%BACKEND_DIR%\.venv\Scripts\python.exe"

if not exist "%BACKEND_PYTHON%" (
    echo venv not found at %BACKEND_PYTHON% - create it first.
    goto :done
)

pushd "%BACKEND_DIR%"
"%BACKEND_PYTHON%" prepare_ingestion_demo.py %*
popd

:done
echo.
pause
endlocal
