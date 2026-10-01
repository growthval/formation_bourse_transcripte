<!-- Journal des sessions de travail, la plus récente en haut. -->
# Journal d'itérations — Vigie

## 2026-10-01 (nuit) — Transcriptions YouTube sans Whisper, recherche, chaînes
- **Objectif** : récupérer les transcriptions comme le panneau « Transcription » de YouTube, chercher des
  vidéos par mots-clés ou via des sources externes, suivre les nouvelles vidéos des chaînes.
- **Réalisé** : sous-titres YouTube par défaut dans `vigie video` (piste « fr-orig », `--whisper` sur
  demande, piste audio d'origine pour Whisper) ; `vigie chercher <mots>` (yt-dlp, sans clé d'API) ;
  `vigie chaines` (identifiant « UC… » écrit dans `youtube.csv`) et section « Nouvelles vidéos des chaînes
  suivies » + « Vidéos citées dans les articles » dans `vigie flux` ; flux restants réglés (Corriere, ECFR,
  Times of Israel sans flux ; Brookings lisible) ; Zonebourse pointé sur sa page d'actualités ; vidéo Finary
  dans la file d'attente (BLK-001 résolu).
- **Décisions prises** : aucune nouvelle (LRN-005).
- **Prochaine étape** : `git pull`, `vigie chaines`, `vigie video "https://www.youtube.com/watch?v=UUSUEcZg5Cw"`,
  puis `/analyse-video` dans Claude Code ; ajouter les chaînes YouTube de l'utilisateur dans `youtube.csv`.

## 2026-10-01 (soir) — Mise en route sur la machine locale
- **Objectif** : rattacher le dossier existant `E:\formation` (formation déjà transcrite, environnement en place) au dépôt et valider les flux.
- **Réalisé** : dépôt rattaché par `git init` + `fetch` + `checkout -f` (recette dans le README) ; Deno installé ;
  `vigie sources --tester` : 43 flux OK sur 48. Corrigé ensuite : Corriere (flux figé depuis 2024) et WSJ
  (figé depuis janvier 2025) remplacés, Kyiv Independent sans flux (404), lecteur tolérant aux entités HTML
  (Brookings), au texte avant l'en-tête XML (Opinio Juris) et aux refus 403 (ECFR, Times of Israel : second
  essai avec un en-tête de navigateur) ; flux figés signalés « FIGÉ » ; lignes CSV mal formées signalées.
- **Décisions prises** : aucune nouvelle (LRN-004).
- **Prochaine étape** : `git pull` dans `E:\formation`, relancer `vigie sources --tester`, puis ouvrir Claude Code :
  `/formation synthèse`, `/veille`, `/analyse-video` (vidéo Finary), `/anticiper revue`.

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
