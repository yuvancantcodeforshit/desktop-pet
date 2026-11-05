@echo off
cd /d "%~dp0"
if not defined LOCALAPPDATA exit /b 1
set "D=%LOCALAPPDATA%\Programs\DesktopPet"
set "SYS=%SystemRoot%\System32"
rem Same stop as install.cmd: inner process first so the launcher cleans up its temp folder.
"%SYS%\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'DesktopPet.exe' -and (Get-Process -Id $_.ParentProcessId -EA 0).Name -eq 'DesktopPet' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; Wait-Process -Name DesktopPet -Timeout 10 -EA 0; Stop-Process -Name DesktopPet -Force -EA 0"
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Desktop Pet.lnk" 2>nul
"%SYS%\reg.exe" delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DesktopPet" /f >nul 2>&1
rem Delete only our own files (incl. updater leftovers); rd without /s keeps anything else the user put there.
rem This script lives in %D%, so finish from a separate process after it exits.
start "" /min "%SYS%\cmd.exe" /c "ping -n 3 127.0.0.1 >nul & cd /d "%TEMP%" & del /q "%D%\DesktopPet.exe" "%D%\DesktopPet.exe.new" "%D%\DesktopPet.exe.old" "%D%\DesktopPet.exe.part" "%D%\uninstall.cmd" 2>nul & rd "%D%" 2>nul"
