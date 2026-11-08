@echo off
rem Starts the whole demonstration in separate windows:
rem   Chapify            http://127.0.0.1:8000
rem   Chapify Pay        http://127.0.0.1:8001   (test payment gateway)
rem   Print station      only if CHAPIFY_STATION_KEY is set
rem Run from Command Prompt in the project folder:  start_demo.bat

cd /d "%~dp0"
if not exist venv\Scripts\activate.bat (
    echo Create the virtual environment first:  python -m venv venv
    exit /b 1
)
call venv\Scripts\activate.bat

python manage.py migrate --noinput || exit /b 1
pushd gateway_service
python manage.py migrate --noinput || (popd & exit /b 1)
start "Chapify Pay - port 8001" cmd /k python manage.py runserver 127.0.0.1:8001
popd

start "Chapify - port 8000" cmd /k python manage.py runserver 127.0.0.1:8000

if defined CHAPIFY_STATION_KEY (
    start "Chapify Print Station" cmd /k python -m print_station
) else (
    echo.
    echo No print station started. To start one, copy a key from Printers - Connect a print station, then:
    echo     set CHAPIFY_STATION_KEY=^<key^>
    echo     python -m print_station
)
echo.
echo Chapify:      http://127.0.0.1:8000
echo Chapify Pay:  http://127.0.0.1:8001
