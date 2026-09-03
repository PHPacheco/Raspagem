@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Coletor academico de receitas - execucao segura por padrao.
rem Sem argumentos: consulta a categoria sem acessar paginas /recipe/.
rem fixture: carrega HTML local sem internet.
rem Opcoes extras sao repassadas ao comando collect.

set "ROOT=%~dp0.."
pushd "%ROOT%" >nul 2>&1
if errorlevel 1 (
    echo Nao foi possivel acessar a pasta do projeto.
    exit /b 1
)

if /I "%~1"=="help" goto :help
if /I "%~1"=="--help" goto :help
if /I "%~1"=="fixture" (
    call :find_python
    if errorlevel 1 goto :finish_error
    call :ensure_collection_dependencies
    if errorlevel 1 goto :finish_error
    echo Carregando fixture local, sem acessar a internet...
    "!PYTHON!" -m scraper fixture --database "data\recipes.sqlite"
    set "EXIT_CODE=%ERRORLEVEL%"
    goto :finish
)
if /I "%~1"=="init-db" goto :init_db

call :find_python
if errorlevel 1 goto :finish_error
call :ensure_collection_dependencies
if errorlevel 1 goto :finish_error

if "%~1"=="" (
    set "COLLECT_ARGS=--max-pages 1 --discover-only"
) else (
    set "COLLECT_ARGS=%*"
)

echo Executando coletor com: %COLLECT_ARGS%
"%PYTHON%" -m scraper collect --category-url "https://www.tudogostoso.com.br/categorias/1004-carnes" --database "data\recipes.sqlite" %COLLECT_ARGS%
set "EXIT_CODE=%ERRORLEVEL%"
goto :finish

:init_db
call :find_python
if errorlevel 1 goto :finish_error
call :ensure_collection_dependencies
if errorlevel 1 goto :finish_error
"%PYTHON%" -m scraper init-db --database "data\recipes.sqlite"
set "EXIT_CODE=%ERRORLEVEL%"
goto :finish

:find_python
set "PYTHON="
if exist "%ROOT%\.venv\Scripts\python.exe" set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
if not defined PYTHON if exist "%ROOT%\.venv\bin\python.exe" set "PYTHON=%ROOT%\.venv\bin\python.exe"
if defined PYTHON exit /b 0

where python >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=python"
    echo Python encontrado no PATH.
    if not exist "%ROOT%\.venv\Scripts\python.exe" if not exist "%ROOT%\.venv\bin\python.exe" (
        echo Criando ambiente virtual .venv...
        python -m venv "%ROOT%\.venv"
        if errorlevel 1 (
            echo Nao foi possivel criar o ambiente virtual.
            exit /b 1
        )
        if exist "%ROOT%\.venv\Scripts\python.exe" set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
        if exist "%ROOT%\.venv\bin\python.exe" set "PYTHON=%ROOT%\.venv\bin\python.exe"
    )
    exit /b 0
)

echo Python nao foi encontrado. Tentando instalar Python 3.12 para o usuario...
where winget >nul 2>&1
if errorlevel 1 (
    echo O comando winget nao esta disponivel.
    echo Instale Python 3.12 manualmente em https://www.python.org/downloads/
    exit /b 1
)
winget install --id Python.Python.3.12 --exact --scope user --accept-source-agreements --accept-package-agreements
if errorlevel 1 (
    echo A instalacao do Python falhou ou foi cancelada.
    exit /b 1
)
where python >nul 2>&1
if errorlevel 1 (
    echo Feche e abra novamente o terminal para atualizar o PATH.
    exit /b 1
)
set "PYTHON=python"
python -m venv "%ROOT%\.venv"
if errorlevel 1 exit /b 1
if exist "%ROOT%\.venv\Scripts\python.exe" set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
if exist "%ROOT%\.venv\bin\python.exe" set "PYTHON=%ROOT%\.venv\bin\python.exe"
exit /b 0

:ensure_collection_dependencies
"%PYTHON%" -c "import bs4, requests" >nul 2>&1
if not errorlevel 1 exit /b 0
echo Dependencias de coleta ausentes. Baixando beautifulsoup4 e requests...
"%PYTHON%" -m pip install beautifulsoup4 requests
if errorlevel 1 (
    echo Nao foi possivel instalar as dependencias.
    exit /b 1
)
exit /b 0

:help
echo.
echo Uso:
echo   bats\coletar_receitas.bat
echo       Descobre somente a primeira pagina, sem acessar /recipe/.
echo.
echo   bats\coletar_receitas.bat fixture
echo       Carrega os HTMLs de teste locais no SQLite.
echo.
echo   bats\coletar_receitas.bat --max-pages 2 --discover-only
echo       Descobre links em duas paginas, sem detalhes das receitas.
echo.
echo   bats\coletar_receitas.bat --max-pages 2 --allow-authorized-recipe-pages --override-robots-with-permission
echo       Coleta detalhes somente com autorizacao especifica.
echo.
echo O script cria .venv e instala beautifulsoup4/requests quando necessario.
set "EXIT_CODE=0"
goto :finish

:finish_error
set "EXIT_CODE=1"

:finish
popd >nul 2>&1
exit /b %EXIT_CODE%
