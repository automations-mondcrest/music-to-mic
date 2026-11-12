@echo off
rem Music to Mic installer: installs the two Python packages and puts a shortcut on your desktop.
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
%PY% --version >nul 2>nul || (
  echo Python was not found. Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^), then run this again.
  pause & exit /b 1
)
echo Installing numpy and sounddevice...
%PY% -m pip install --user -r requirements.txt || (echo pip failed. & pause & exit /b 1)
for /f "delims=" %%i in ('%PY% -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set "PYW=%%i"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Music to Mic.lnk'); $s.TargetPath='%PYW%'; $s.Arguments='\"%~dp0music_to_mic.pyw\"'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0icon.ico'; $s.Save()"
echo.
echo Done. A "Music to Mic" shortcut is on your desktop.
echo You also need VB-Audio Virtual Cable: https://vb-audio.com/Cable/
pause
