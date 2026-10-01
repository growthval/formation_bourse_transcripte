"""Vigie : outils de veille du projet (vidéos YouTube, flux de presse, registre des sources).

Trois commandes (``python -m vigie`` ou ``vigie.bat`` sous Windows) :

- ``video``   : récupère une vidéo (sous-titres ou audio + Whisper) et prépare sa fiche d'analyse ;
- ``flux``    : digest Markdown des derniers articles des sources (flux RSS/Atom) ;
- ``sources`` : vérifie le registre des sources et teste les flux.
"""

from __future__ import annotations

from pathlib import Path

__version__ = "0.1.0"

# Racine du dépôt : les chemins par défaut (veille/, connaissances/, modeles/) y sont relatifs,
# quel que soit le dossier d'où la commande est lancée.
RACINE = Path(__file__).resolve().parent.parent
