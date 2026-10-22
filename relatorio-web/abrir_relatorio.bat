@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions

set "REPORT=%~dp0index.html"
if not exist "%REPORT%" (
    echo Relatorio nao encontrado em: %REPORT%
    pause
    exit /b 1
)

start "" "%REPORT%"
exit /b 0
