@echo off
title Create Desktop Shortcut

:: Creates a "RAS Tips" shortcut on the Desktop pointing to run.bat in this folder.

powershell -command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$desktop = [Environment]::GetFolderPath('Desktop');" ^
  "$s = $ws.CreateShortcut($desktop + '\RAS Tips.lnk');" ^
  "$s.TargetPath = '%~dp0run.bat';" ^
  "$s.WorkingDirectory = '%~dp0';" ^
  "$s.Description = 'RAS Tips Generator';" ^
  "$s.Save();"

echo.
echo  Shortcut "RAS Tips" has been created on your Desktop.
echo  Double-click it any time to launch the app with the latest version.
echo.
pause
