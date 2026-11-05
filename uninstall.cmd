@echo off
cd /d "%~dp0"
if not defined LOCALAPPDATA exit /b 1
set "D=%LOCALAPPDATA%\Programs\DesktopPet"
set "SYS=%SystemRoot%\System32"
"%SYS%\taskkill.exe" /im DesktopPet.exe /f >nul 2>&1
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Desktop Pet.lnk" 2>nul
"%SYS%\reg.exe" delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DesktopPet" /f >nul 2>&1
rem Delete only our own files (incl. updater leftovers); rd without /s keeps anything else the user put there.
rem This script lives in %D%, so finish from a separate process after it exits.
start "" /min "%SYS%\cmd.exe" /c "ping -n 3 127.0.0.1 >nul & cd /d "%TEMP%" & del /q "%D%\DesktopPet.exe" "%D%\DesktopPet.exe.new" "%D%\DesktopPet.exe.old" "%D%\DesktopPet.exe.part" "%D%\uninstall.cmd" 2>nul & rd "%D%" 2>nul"
