@echo off
cd /d "%~dp0"
echo Lancement du serveur et du tunnel public...
start "Serveur IA (local)" cmd /k ".\venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"
timeout /t 3 /nobreak >nul
start "Tunnel public (URL pour ton telephone)" cmd /k ".\tools\cloudflared.exe tunnel --url http://localhost:8000"
echo.
echo Deux fenetres se sont ouvertes :
echo   - "Serveur IA (local)"           = le backend, ne pas fermer
echo   - "Tunnel public"                = regarde cette fenetre pour trouver
echo                                      l'URL en https://....trycloudflare.com
echo                                      a ouvrir sur ton telephone.
echo.
pause
