@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONDONTWRITEBYTECODE=1
set "_ROOT=%~dp0"
if exist "%_ROOT%runtime\python\python.exe" (
  set "PATH=%_ROOT%runtime\python;%_ROOT%runtime\python\Library\bin;%_ROOT%runtime\python\DLLs;%PATH%"
  "%_ROOT%runtime\python\python.exe" -B "%_ROOT%scripts\start_demo.py" --python "%_ROOT%runtime\python\python.exe" %*
  goto runtime_finish
)
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3.10 -B "%~dp0scripts\start_demo.py" %*
set "_DEMO_EXIT=%errorlevel%"
goto finish
:use_python
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.10 was not found. Install Python 3.10 and rerun this launcher.
  set "_DEMO_EXIT=2"
  goto finish
)
python -B "%~dp0scripts\start_demo.py" %*
set "_DEMO_EXIT=%errorlevel%"
goto finish
:runtime_finish
set "_DEMO_EXIT=%errorlevel%"
:finish
if "%~1"=="" if not "%_DEMO_EXIT%"=="0" pause
exit /b %_DEMO_EXIT%
