@echo off
setlocal
cd /d "%~dp0"
echo === Step 1/2: PyInstaller build (one-dir) ===
python -m PyInstaller --noconfirm --clean app.spec
if errorlevel 1 goto fail
echo === Step 2/2: copy model(可选) + ffmpeg next to app ===
if exist "dist\ImageTagger\eva02" rmdir /s /q "dist\ImageTagger\eva02"
if exist "..\eva02" (
  xcopy "..\eva02" "dist\ImageTagger\eva02\" /E /I /Q
) else (
  echo [提示] 未找到 ..\eva02 模型目录，已跳过；程序首次运行会自动下载模型。
)
if exist "dist\ImageTagger\ffmpeg" rmdir /s /q "dist\ImageTagger\ffmpeg"
if exist "ffmpeg" xcopy "ffmpeg" "dist\ImageTagger\ffmpeg\" /E /I /Q
echo.
echo Done. Package at: dist\ImageTagger
echo Next: run build_setup.bat to make the installer.
pause
exit /b 0
:fail
echo Build FAILED.
pause
exit /b 1
