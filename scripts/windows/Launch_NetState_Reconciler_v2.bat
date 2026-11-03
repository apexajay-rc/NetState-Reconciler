@echo off
setlocal EnableExtensions

rem NetState Reconciler 1.2.0 - Windows one-click launcher
rem Can live in the project root OR one folder below it (ZIP extraction folder).

set "LAUNCH_DIR=%~dp0"
set "NSR_HOME="

if exist "%LAUNCH_DIR%app.py" set "NSR_HOME=%LAUNCH_DIR%"
if not defined NSR_HOME (
    for %%I in ("%LAUNCH_DIR%..") do if exist "%%~fI\app.py" set "NSR_HOME=%%~fI\"
)
if not defined NSR_HOME (
    for %%I in ("%LAUNCH_DIR%..\..") do if exist "%%~fI\app.py" set "NSR_HOME=%%~fI\"
)

if not defined NSR_HOME (
    title NetState Reconciler - Project Not Found
    echo.
    echo  ===============================================
    echo       NETSTATE RECONCILER - ONE-CLICK START
    echo  ===============================================
    echo.
    echo ERROR: Could not locate app.py.
    echo.
    echo Put this launcher inside the NetState-Reconciler folder,
    echo or keep it in a subfolder directly inside that folder.
    echo.
    echo Launcher location: %LAUNCH_DIR%
    echo Expected project file: app.py
    echo.
    pause
    exit /b 1
)

if "%NSR_HOME:~-1%"=="\" set "NSR_HOME=%NSR_HOME:~0,-1%"
set "PYTHON=%NSR_HOME%\.venv\Scripts\python.exe"
set "MCP_ENDPOINT=http://127.0.0.1:39400/mcp"
set "NSR_PORT=8501"

if /i "%~1"=="--mcp" goto RUN_MCP
if /i "%~1"=="--web" goto RUN_WEB

title NetState Reconciler Launcher
echo.
echo  ===============================================
echo       NETSTATE RECONCILER - ONE-CLICK START
echo  ===============================================
echo.
echo Project folder: %NSR_HOME%
echo.

if not exist "%PYTHON%" (
    echo ERROR: Project virtual-environment Python was not found:
    echo %PYTHON%
    echo.
    echo From the project folder, run:
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -e ".[dev]"
    goto MAIN_ERROR
)

"%PYTHON%" -c "import streamlit, packet_tracer_mcp" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Streamlit or Packet Tracer MCP is missing from the project environment.
    echo Run this once from the project folder:
    echo   .venv\Scripts\python.exe -m pip install -e ".[dev]"
    goto MAIN_ERROR
)

if not exist "%NSR_HOME%\.netstate" mkdir "%NSR_HOME%\.netstate" >nul 2>&1
if not exist "%NSR_HOME%\.netstate\checkpoints" mkdir "%NSR_HOME%\.netstate\checkpoints" >nul 2>&1
if not exist "%NSR_HOME%\.netstate\reports" mkdir "%NSR_HOME%\.netstate\reports" >nul 2>&1
if not exist "%NSR_HOME%\.netstate\snapshots" mkdir "%NSR_HOME%\.netstate\snapshots" >nul 2>&1
if not exist "%NSR_HOME%\logs" mkdir "%NSR_HOME%\logs" >nul 2>&1

rem Locate Cisco Packet Tracer in common install directories.
set "PT_EXE="
for /d %%D in ("%ProgramFiles%\Cisco Packet Tracer*") do (
    if exist "%%~fD\bin\PacketTracer.exe" set "PT_EXE=%%~fD\bin\PacketTracer.exe"
)
if not defined PT_EXE if defined ProgramFiles(x86) (
    for /d %%D in ("%ProgramFiles(x86)%\Cisco Packet Tracer*") do (
        if exist "%%~fD\bin\PacketTracer.exe" set "PT_EXE=%%~fD\bin\PacketTracer.exe"
    )
)

rem Launch Packet Tracer if it is not already running.
tasklist /FI "IMAGENAME eq PacketTracer.exe" 2>nul | find /I "PacketTracer.exe" >nul
if errorlevel 1 (
    if defined PT_EXE (
        echo [1/3] Launching Cisco Packet Tracer...
        start "" "%PT_EXE%"
    ) else (
        echo [1/3] WARNING: PacketTracer.exe was not found in standard install folders.
        echo       Start Packet Tracer manually. NSR startup will continue.
    )
) else (
    echo [1/3] Cisco Packet Tracer is already running.
)

echo       Waiting briefly for Packet Tracer to initialize...
timeout /t 6 /nobreak >nul

rem Start MCP unless port 39400 already has a listener.
netstat -ano -p tcp | findstr /R /C:":39400 .*LISTENING" >nul
if errorlevel 1 (
    echo [2/3] Starting Packet Tracer MCP server on port 39400...
    start "NSR - Packet Tracer MCP" "%ComSpec%" /k ""%~f0" --mcp"
) else (
    echo [2/3] Port 39400 already has a listener; not starting a duplicate MCP server.
)

set "MCP_READY="
for /L %%I in (1,1,15) do (
    netstat -ano -p tcp | findstr /R /C:":39400 .*LISTENING" >nul
    if not errorlevel 1 set "MCP_READY=1"
    if defined MCP_READY goto MCP_WAIT_FINISHED
    timeout /t 1 /nobreak >nul
)
:MCP_WAIT_FINISHED
if defined MCP_READY (
    echo       MCP HTTP listener detected on port 39400.
) else (
    echo       WARNING: MCP did not open port 39400. Check its terminal window.
)

rem Start Streamlit unless port 8501 already has a listener.
netstat -ano -p tcp | findstr /R /C:":8501 .*LISTENING" >nul
if errorlevel 1 (
    echo [3/3] Starting NetState Reconciler web application on port 8501...
    start "NSR - Streamlit Web Application" "%ComSpec%" /k ""%~f0" --web"
) else (
    echo [3/3] Port 8501 already has a listener; reusing the existing web service.
)

set "WEB_READY="
for /L %%I in (1,1,30) do (
    curl.exe --silent --max-time 1 --output NUL "http://127.0.0.1:%NSR_PORT%/" >nul 2>&1
    if not errorlevel 1 set "WEB_READY=1"
    if defined WEB_READY goto WEB_WAIT_FINISHED
    timeout /t 1 /nobreak >nul
)
:WEB_WAIT_FINISHED
if defined WEB_READY (
    echo       Opening NetState Reconciler in your browser...
    start "" "http://127.0.0.1:%NSR_PORT%"
) else (
    echo       WARNING: NSR web UI did not respond within 30 seconds.
    echo       Check the Streamlit terminal window.
)

echo.
echo  Startup commands have been launched.
echo.
echo  Packet Tracer's MCP Control Center extension must already be
 echo  registered and enabled. If its panel is not open, open it manually.
echo.
echo  NSR URL: %MCP_ENDPOINT%
echo  Web UI : http://127.0.0.1:%NSR_PORT%
echo.
echo  The MCP and Streamlit terminal windows must remain open.
echo  Press any key to close this launcher window.
pause >nul
exit /b 0

:RUN_MCP
cd /d "%NSR_HOME%"
echo Starting Packet Tracer MCP 0.10.2 at %MCP_ENDPOINT%
"%PYTHON%" -u -m packet_tracer_mcp
echo.
echo MCP server process exited. Read the error above.
pause
exit /b

:RUN_WEB
cd /d "%NSR_HOME%"
set "NETSTATE_MCP_ENDPOINT=%MCP_ENDPOINT%"
set "NETSTATE_PORT=%NSR_PORT%"
echo Starting NetState Reconciler 1.2.0 at http://127.0.0.1:%NSR_PORT%
"%PYTHON%" -m streamlit run "%NSR_HOME%\app.py" --server.address 127.0.0.1 --server.port %NSR_PORT% --server.headless true
echo.
echo Streamlit process exited. Read the error above.
pause
exit /b

:MAIN_ERROR
echo.
pause
exit /b 1
