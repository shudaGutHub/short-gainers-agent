@echo off
REM ============================================================
REM Short Gainers Agent - Scheduled Auto-Refresh
REM Runs analysis on top gainers and deploys to Netlify
REM ============================================================

setlocal

set "PROJECT_DIR=%~dp0"
set "LOG_DIR=%PROJECT_DIR%logs"
set "VENV_DIR=%PROJECT_DIR%venv"

REM Create logs directory if it doesn't exist
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM Log file with date stamp (locale-independent via wmic)
for /f "tokens=2 delims==" %%a in ('wmic os get localdatetime /value') do set "DT=%%a"
set "DATESTAMP=%DT:~0,4%-%DT:~4,2%-%DT:~6,2%"
set "TIMESTAMP=%DT:~8,2%%DT:~10,2%"
set "LOG_FILE=%LOG_DIR%\run_%DATESTAMP%_%TIMESTAMP%.log"

echo ============================================================ >> "%LOG_FILE%"
echo Run started: %date% %time% >> "%LOG_FILE%"
echo ============================================================ >> "%LOG_FILE%"

REM Activate virtual environment
call "%VENV_DIR%\Scripts\activate.bat"

REM Run the analysis with deploy
python -m src.batch_cli --top-gainers --extra-tickers-file "%PROJECT_DIR%watchlist.txt" --deploy --netlify-site 016ab674-a973-46a3-b463-8db18018b182 >> "%LOG_FILE%" 2>&1

echo. >> "%LOG_FILE%"
echo Run finished: %date% %time% >> "%LOG_FILE%"
echo Exit code: %ERRORLEVEL% >> "%LOG_FILE%"

REM Keep only last 50 log files
for /f "skip=50 delims=" %%f in ('dir /b /o-d "%LOG_DIR%\run_*.log" 2^>nul') do del "%LOG_DIR%\%%f"

endlocal
