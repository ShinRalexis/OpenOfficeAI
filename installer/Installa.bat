@echo off
rem OpenOfficeAI: installa o aggiorna l'estensione (doppio clic).
rem Parametri facoltativi: -CloseOffice  -Uninstall
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
pause
