@echo off
setlocal
cd /d "%~dp0"
echo Building installer with Inno Setup 6 ...
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
  goto :done
)
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
  "C:\Program Files\Inno Setup 6\ISCC.exe" installer.iss
  goto :done
)
echo ISCC.exe not found. Install Inno Setup 6 first.
pause
exit /b 1
:done
echo Installer at: dist_setup\
pause
