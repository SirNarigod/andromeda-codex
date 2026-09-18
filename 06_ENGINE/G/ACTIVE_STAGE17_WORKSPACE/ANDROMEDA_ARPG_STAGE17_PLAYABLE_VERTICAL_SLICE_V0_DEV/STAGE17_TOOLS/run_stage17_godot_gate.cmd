@echo off
setlocal
set "GODOT_EXE=C:\Program Files\Godot\Godot.exe"
set "WORKSPACE=%~dp0.."
set "PROJECT_DIR=%WORKSPACE%\13_GODOT_ARPG_STAGE17"
set "APPDATA=%WORKSPACE%\STAGE17_RUNTIME_STATE\GodotAppData"

if "%~1"=="" (
  echo SCENE_ARGUMENT_REQUIRED 1>&2
  exit /b 64
)
if "%~2"=="" (
  echo LOG_ARGUMENT_REQUIRED 1>&2
  exit /b 64
)
if not exist "%GODOT_EXE%" (
  echo GODOT_EXECUTABLE_NOT_FOUND 1>&2
  exit /b 66
)
if not exist "%PROJECT_DIR%\project.godot" (
  echo STAGE17_PROJECT_NOT_FOUND 1>&2
  exit /b 66
)
if not exist "%APPDATA%" mkdir "%APPDATA%"

"%GODOT_EXE%" --headless --log-file "%~2" --path "%PROJECT_DIR%" "%~1" -- --gate-success-linger=0 %~3
set "GODOT_EXIT_CODE=%ERRORLEVEL%"
echo GODOT_EXIT_CODE=%GODOT_EXIT_CODE%
exit /b %GODOT_EXIT_CODE%
