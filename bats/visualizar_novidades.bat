@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions EnableDelayedExpansion

rem Atalho para visualizar as novidades em notebook.
rem Este fluxo substitui a antiga pagina Streamlit: agora tudo fica em um .ipynb
rem com outputs prontos, separado em blocos de estudo.

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "ROOT=%~dp0.."
set "DATABASE=data\recipes.sqlite"
set "NOTEBOOK=notebooks\Trabalho PLN.ipynb"
set "SKIP_INSTALL=0"
set "NO_OPEN=0"
set "NO_PAUSE=0"

pushd "%ROOT%" >nul 2>&1
if errorlevel 1 (
    echo Nao foi possivel acessar a pasta do projeto.
    exit /b 1
)

:parse_args
if "%~1"=="" goto :start
if /I "%~1"=="help" goto :help
if /I "%~1"=="--help" goto :help
if /I "%~1"=="/?" goto :help
if /I "%~1"=="--skip-install" (
    set "SKIP_INSTALL=1"
    shift
    goto :parse_args
)
if /I "%~1"=="--no-open" (
    set "NO_OPEN=1"
    shift
    goto :parse_args
)
if /I "%~1"=="--no-app" (
    rem Compatibilidade com a versao antiga do BAT.
    set "NO_OPEN=1"
    shift
    goto :parse_args
)
if /I "%~1"=="--no-pause" (
    set "NO_PAUSE=1"
    shift
    goto :parse_args
)
echo Opcao desconhecida: %~1
echo Use bats\visualizar_novidades.bat --help para ver as opcoes.
set "EXIT_CODE=1"
goto :finish

:start
call :find_python
if errorlevel 1 goto :finish_error

if "%SKIP_INSTALL%"=="0" (
    call :ensure_dependencies
    if errorlevel 1 goto :finish_error
) else (
    echo Instalacao de dependencias ignorada por --skip-install.
)

if not exist "%DATABASE%" (
    echo Banco %DATABASE% nao encontrado.
    echo Carregando fixture local para criar dados demonstrativos, sem acessar a internet...
    "%PYTHON%" -m scraper fixture --database "%DATABASE%" --log-file "logs\visualizar-novidades-fixture.jsonl"
    if errorlevel 1 goto :finish_error
) else (
    echo Banco %DATABASE% encontrado. Vou atualizar as analises sobre os dados existentes.
)

echo.
echo Gerando limpeza/preparacao, matriz TF-IDF, similaridades, clusters e projecao 3D...
"%PYTHON%" -m scraper analyze-texts --database "%DATABASE%"
if errorlevel 1 goto :finish_error

echo.
echo Gerando embeddings densos da etapa 7...
"%PYTHON%" -m scraper build-embeddings --database "%DATABASE%"
if errorlevel 1 goto :finish_error

echo.
echo Gerando notebook com outputs prontos...
"%PYTHON%" -m scraper export-notebook --database "%DATABASE%" --output "%NOTEBOOK%"
if errorlevel 1 goto :finish_error

echo.
echo Notebook gerado em: %NOTEBOOK%

if "%NO_OPEN%"=="1" (
    set "EXIT_CODE=0"
    goto :finish
)

where code >nul 2>&1
if not errorlevel 1 (
    echo Abrindo no VS Code...
    code "%NOTEBOOK%"
    set "EXIT_CODE=0"
    goto :finish
)

echo Abrindo com o aplicativo padrao do Windows...
start "" "%NOTEBOOK%"
set "EXIT_CODE=0"
goto :finish

:find_python
set "PYTHON="
if exist "%ROOT%\.venv\Scripts\python.exe" set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
if not defined PYTHON if exist "%ROOT%\.venv\bin\python.exe" set "PYTHON=%ROOT%\.venv\bin\python.exe"
if defined PYTHON exit /b 0

where python >nul 2>&1
if errorlevel 1 (
    echo Python nao foi encontrado no PATH.
    echo Instale Python 3.12 manualmente em https://www.python.org/downloads/
    exit /b 1
)

echo Criando ambiente virtual .venv...
python -m venv "%ROOT%\.venv"
if errorlevel 1 (
    echo Nao foi possivel criar o ambiente virtual.
    exit /b 1
)

if exist "%ROOT%\.venv\Scripts\python.exe" set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
if not defined PYTHON if exist "%ROOT%\.venv\bin\python.exe" set "PYTHON=%ROOT%\.venv\bin\python.exe"
if not defined PYTHON (
    echo Ambiente virtual criado, mas o Python interno nao foi encontrado.
    exit /b 1
)
exit /b 0

:ensure_dependencies
"%PYTHON%" -c "import bs4, requests" >nul 2>&1
if not errorlevel 1 exit /b 0

echo Instalando dependencias do projeto...
"%PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Nao foi possivel instalar as dependencias.
    exit /b 1
)
exit /b 0

:help
echo.
echo Uso:
echo   bats\visualizar_novidades.bat
echo       Prepara as analises, gera o notebook e abre o .ipynb.
echo.
echo   bats\visualizar_novidades.bat --no-open
echo       Gera/atualiza o notebook, mas nao tenta abrir o arquivo.
echo.
echo   bats\visualizar_novidades.bat --skip-install
echo       Nao tenta instalar dependencias antes de executar.
echo.
echo   bats\visualizar_novidades.bat --no-pause
echo       Nao espera tecla em caso de erro. Util para executar pelo terminal.
echo.
echo O que voce vera no notebook:
echo   - dados coletados e filtros;
echo   - limpeza e preparacao textual;
echo   - grafico 3D, TF-IDF, similaridade e clusters;
echo   - etapa 7 com embeddings densos e vizinhos por contexto.
echo.
set "EXIT_CODE=0"
goto :finish

:finish_error
set "EXIT_CODE=1"

:finish
if not "%EXIT_CODE%"=="0" (
    echo.
    echo Ocorreu um erro. A janela ficara aberta para voce copiar a mensagem acima.
    if "%NO_PAUSE%"=="0" pause
)
popd >nul 2>&1
exit /b %EXIT_CODE%
