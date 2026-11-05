@echo off
rem Per-user install: no admin needed.
rem Run from this script's own (private) folder so planted exes in Downloads are never picked up.
cd /d "%~dp0"
if not defined LOCALAPPDATA exit /b 1
set "D=%LOCALAPPDATA%\Programs\DesktopPet"
set "K=HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DesktopPet"
set "SYS=%SystemRoot%\System32"
rem Stop a running pet: kill only the inner process so its launcher deletes its %TEMP%\_MEI folder, then wait.
"%SYS%\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'DesktopPet.exe' -and (Get-Process -Id $_.ParentProcessId -EA 0).Name -eq 'DesktopPet' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; Wait-Process -Name DesktopPet -Timeout 10 -EA 0; Stop-Process -Name DesktopPet -Force -EA 0"
if not exist "%D%" mkdir "%D%"
copy /y "%~dp0DesktopPet.exe" "%D%\" >nul || exit /b 1
copy /y "%~dp0uninstall.cmd" "%D%\" >nul || exit /b 1
rem Path goes in via $env:D, not pasted into the string, so a ' in the username can't break it.
"%SYS%\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:APPDATA+'\Microsoft\Windows\Start Menu\Programs\Desktop Pet.lnk'); $s.TargetPath=$env:D+'\DesktopPet.exe'; $s.Save()"
rem Shows up in Settings > Apps, with an Uninstall button
"%SYS%\reg.exe" add "%K%" /v DisplayName /d "Desktop Pet" /f >nul
"%SYS%\reg.exe" add "%K%" /v DisplayIcon /d "%D%\DesktopPet.exe" /f >nul
"%SYS%\reg.exe" add "%K%" /v UninstallString /d "\"%D%\uninstall.cmd\"" /f >nul
"%SYS%\reg.exe" add "%K%" /v NoModify /t REG_DWORD /d 1 /f >nul
"%SYS%\reg.exe" add "%K%" /v NoRepair /t REG_DWORD /d 1 /f >nul
rem /d: pet must not keep this installer's temp folder as its cwd, or the folder can't be deleted
start "" /d "%D%" "%D%\DesktopPet.exe"
