@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Panela Aberta

pushd "%~dp0" || exit /b 1

where npm.cmd >nul 2>&1
if errorlevel 1 goto :no_node
node -e "if (Number(process.versions.node.split('.')[0]) < 22) process.exit(1)" >nul 2>&1
if errorlevel 1 goto :no_node

node -e "const socket = require('node:net').createServer(); socket.once('error', () => process.exit(1)); socket.listen(8788, '127.0.0.1', () => socket.close());" >nul 2>&1
if errorlevel 1 (
    echo A porta 8788 esta ocupada. Feche o servidor anterior e tente novamente.
    goto :failed
)

if not exist "node_modules\.bin\wrangler.cmd" (
    echo Instalando as dependencias do Panela Aberta...
    call npm.cmd ci --no-audit --no-fund
    if errorlevel 1 (
        echo A instalacao falhou. Confira a mensagem do npm acima.
        goto :failed
    )
)

set "PANELA_ABERTA_URL=http://127.0.0.1:8788"
echo Panela Aberta em %PANELA_ABERTA_URL%
echo Deixe esta janela aberta. Use Ctrl+C para parar o servidor.
echo.

rem Abra o navegador somente quando a pagina estiver pronta.
start "" /b powershell.exe -NoProfile -NonInteractive -Command "$ProgressPreference = 'SilentlyContinue'; $url = $env:PANELA_ABERTA_URL; for ($i = 0; $i -lt 45; $i++) { try { $page = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2; if ($page.Content -like '*<title>Panela Aberta*') { Start-Process -FilePath $url; exit } } catch {}; Start-Sleep -Milliseconds 1000 }"
call npm.cmd run dev -- --ip 127.0.0.1 --port 8788
if errorlevel 1 (
    echo O servidor encerrou com erro. Confira a mensagem do Wrangler acima.
    goto :failed
)
popd
exit /b 0

:no_node
echo Instale o Node.js 22 ou superior com npm e abra este arquivo novamente.
:failed
popd
pause
exit /b 1
