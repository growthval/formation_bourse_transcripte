---
paths:
  - "podia_formation/**"
  - "vigie/**"
  - "tests/**"
  - "*.bat"
---
# Code Python du dépôt

- **Français partout** : commandes, options, messages et commentaires (`--forcer`, « ATTENTION : », « OK : »,
  « ERREUR : »), comme dans `podia_formation`. Noms de variables en anglais acceptés.
- **Bibliothèque standard d'abord.** Une dépendance nouvelle doit se justifier (Windows sans compilateur,
  pas de ffmpeg à installer) et s'ajouter dans `requirements.txt` avec sa version testée.
- **Tests hors ligne** : `pytest` ne doit jamais toucher le réseau ; yt-dlp, Whisper et les flux RSS sont
  remplacés par des doublures (voir `tests/test_vigie_*.py`, `tests/fake_podia.py`).
- **Reprise** : toute commande longue est relançable, ce qui est fait est conservé, `--forcer` refait.
- **Windows d'abord** : chemins courts (limite de 260 caractères), noms de fichiers via `safe_filename`,
  encodage UTF-8 explicite à chaque lecture/écriture, lanceurs `.bat`.
- **Sorties de l'outil** : `formation/` et `veille/videos/*/audio.m4a` sont des produits régénérables,
  ignorés par git ; ne jamais les modifier à la main depuis le code.
- Avant de livrer : `python -m pytest -q` vert, et `python -m vigie --help` / `python -m podia_formation --help` fonctionnels.
