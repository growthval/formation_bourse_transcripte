@echo off
rem Lance l'outil sans avoir a activer l'environnement : formation sonde "adresse", formation audio "adresse"...
chcp 65001 >nul
"%~dp0.venv\Scripts\python.exe" -m podia_formation %*
