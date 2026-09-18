@echo off
setlocal
set "GODOT_EXE=C:\Program Files\Godot\Godot.exe"
set "PROJECT_DIR=C:\Users\thall\Documents\andromeda-argp\ANDROMEDA_ARPG_GODOT_STAGE16A_V1_7_0_DEV\07_GODOT_ARPG_STAGE16B"

if "%~1"=="" (
  echo SCENE_ARGUMENT_REQUIRED 1>&2
  exit /b 64
)
if "%~2"=="" (
  echo LOG_ARGUMENT_REQUIRED 1>&2
  exit /b 64
)

"%GODOT_EXE%" --headless --log-file "%~2" --path "%PROJECT_DIR%" "%~1" -- --gate-success-linger=0
set "GODOT_EXIT_CODE=%ERRORLEVEL%"
echo GODOT_EXIT_CODE=%GODOT_EXIT_CODE%
exit /b %GODOT_EXIT_CODE%
