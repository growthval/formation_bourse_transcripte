@echo off
rem Outils de veille, sans activer l'environnement : vigie video "adresse", vigie flux, vigie sources --tester
chcp 65001 >nul
"%~dp0.venv\Scripts\python.exe" -m vigie %*
