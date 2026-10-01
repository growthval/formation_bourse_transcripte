<!-- Journal des sessions de travail, la plus récente en haut. -->
# Journal d'itérations — Vigie

## 2026-10-01 — Création de la structure du projet
- **Objectif** : transformer le dépôt de l'outil de transcription en projet de veille, d'aide à
  l'investissement et d'anticipation, structuré avec Structure Maker.
- **Réalisé** : constitution `CLAUDE.md` ; agents `chercheur`, `analyste`, `auditeur` ; règles ciblées ;
  skills `/veille`, `/analyse-video`, `/croiser`, `/dossier`, `/formation`, `/anticiper` (renommé depuis `/plan`, nom réservé par Claude Code), `/log` ; mémoire ;
  soul/user ; méthode (charte, sources, grille de lecture, prévision) ; registres de sources (médias,
  chaînes, personnes) ; modèles de documents ; paquet `vigie` (vidéo, flux, sources) avec 18 tests ;
  squelettes `veille/` (dossiers thématiques et pays, backlog) et `plan/` (scénarios, signaux, pivot).
- **Décisions prises** : DEC-001 à DEC-005.
- **Prochaine étape** : installer en local, générer la transcription de la formation, valider les flux
  RSS (`vigie sources --tester`), analyser la vidéo Finary, lancer la première `/veille`.
