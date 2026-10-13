@echo off
rem ---------------------------------------------------------------------------
rem AgriSureGIS - root launcher for the typhoon simulations.
rem
rem Thin wrapper only: it pushd's into backend\ and runs the real script from
rem backend\simulation\ with that venv, because those scripts import the `app`
rem package and so need backend\ as the working directory. Same pattern as
rem reset-demo-data.bat.
rem
rem   simulate.bat opong              load OPONG's 23 real PAGASA bulletins
rem   simulate.bat opong --reset      clear OPONG's computed assessment results
rem   simulate.bat alert              simulate a new TCB arriving (dry run)
rem   simulate.bat alert --send       ...and really send the email alert
rem   simulate.bat reparse            re-parse OPONG's saved bulletins (dry run)
rem   simulate.bat track --typhoon OPONG   backfill the track overlay
rem
rem See backend\simulation\README.md for what each one does and the order to
rem run them in. Up to 9 arguments are forwarded.
rem ---------------------------------------------------------------------------
setlocal

set "ROOT=%~dp0"
set "BACKEND_DIR=%ROOT%backend"
set "BACKEND_PYTHON=%BACKEND_DIR%\.venv\Scripts\python.exe"

if not exist "%BACKEND_PYTHON%" (
    echo venv not found at %BACKEND_PYTHON% - create it first.
    goto :done
)

set "TARGET="
if /i "%~1"=="opong"   set "TARGET=seed_opong_assessment_test.py"
if /i "%~1"=="alert"   set "TARGET=simulate_new_bulletin_alert.py"
if /i "%~1"=="reparse" set "TARGET=reparse_opong_bulletins.py"
if /i "%~1"=="track"   set "TARGET=backfill_tcb_track_radius.py"

if not defined TARGET (
    echo Usage: simulate.bat ^<opong^|alert^|reparse^|track^> [arguments]
    echo.
    echo   opong     seed_opong_assessment_test.py   - load OPONG's 23 real bulletins
    echo   alert     simulate_new_bulletin_alert.py  - new-TCB email alert ^(dry run^)
    echo   reparse   reparse_opong_bulletins.py      - re-parse saved bulletins
    echo   track     backfill_tcb_track_radius.py    - backfill the track overlay
    echo.
    echo See backend\simulation\README.md for details.
    goto :done
)

shift

pushd "%BACKEND_DIR%"
"%BACKEND_PYTHON%" "simulation\%TARGET%" %1 %2 %3 %4 %5 %6 %7 %8 %9
popd

:done
echo.
pause
endlocal
