@echo off
rem Installation de l'outil (a lancer une seule fois, par double clic).
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo === Installation de l'outil de formation ===
echo.
set PY=
py -3.12 -c "import sys" >nul 2>nul && set PY=py -3.12
if not defined PY py -3.13 -c "import sys" >nul 2>nul && set PY=py -3.13
if not defined PY python -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,14) else 1)" >nul 2>nul && set PY=python
if not defined PY (
  echo ERREUR : Python 3.12 est introuvable.
  echo Installez-le depuis https://www.python.org/downloads/release/python-31210/
  echo en cochant "Add python.exe to PATH", puis relancez ce fichier.
  pause
  exit /b 1
)
echo Python utilise : %PY%
if not exist .venv\Scripts\python.exe (
  %PY% -m venv .venv || goto erreur
)
.venv\Scripts\python -m pip install --upgrade pip || goto erreur
.venv\Scripts\python -m pip install -r requirements.txt || goto erreur
nvidia-smi >nul 2>nul
if %errorlevel%==0 (
  echo.
  echo Carte graphique NVIDIA detectee : installation des bibliotheques CUDA ^(environ 1 Go^)...
  .venv\Scripts\python -m pip install -r requirements-gpu.txt || goto erreur
)
echo.
echo === Installation terminee ===
echo Prochaine etape : ouvrez une invite de commandes dans ce dossier et tapez
echo   formation sonde "adresse d'une lecon"
echo.
pause
exit /b 0
:erreur
echo.
echo ERREUR pendant l'installation : copiez le message ci-dessus et envoyez-le pour de l'aide.
pause
exit /b 1
