<!--
  Registre des décisions. Trace le POURQUOI de chaque choix. Une entrée = un choix.
  On ajoute, on n'efface pas. Reporter chaque nouvelle entrée dans MEMORY.md (index).
-->
# Décisions — Vigie

## DEC-001 — Structure Maker, tier Avancé allégé
- **Date** : 2026-10-01
- **Contexte** : le projet a été structuré avec le moteur Structure Maker (dépôt `growthval/structure-maker`,
  5 étapes). Fiche projet : veille et aide à la décision, long terme, solo humain + agents, multi-domaine
  (bourse, géopolitique, droit, IA), sensibilité élevée (argent, risque de conclusions fausses).
- **Problème** : quel niveau de gouvernance sans sur-ingénierie ?
- **Décision** : tier Avancé **allégé** : trois agents (`chercheur` sur sonnet, `analyste` sur le modèle de la session, `auditeur` sur opus), trois règles
  ciblées, sept skills, mémoire, settings avec garde-fous, soul/user. **Sans** agent orchestrateur (les
  skills `/veille` et `/dossier` portent elles-mêmes l'ordre des étapes et les dépendances) et **sans
  hooks** (les interdits durs tiennent dans `permissions.deny` : `formation/` protégé en écriture, pas de
  `rm -rf`, pas de `push --force`).
- **Alternatives rejetées** : orchestrateur dédié (une couche de plus sans gain, le fil principal fait
  le routage) ; hooks (aucun interdit n'exige aujourd'hui un blocage à l'exécution : `permissions.deny`
  suffit, et un hook Python resterait possible plus tard) ; `disable-model-invocation` sur les skills
  (voulu : Claude doit pouvoir lancer `/veille` ou `/croiser` de lui-même quand la demande correspond ;
  les écritures restent confinées à `veille/`, `plan/` et la mémoire).
- **Conséquences** : si un workflow devient trop long pour le fil principal, ajouter un orchestrateur ;
  si un interdit doit devenir infranchissable, ajouter un hook Python.

## DEC-002 — Un seul dépôt : outil, connaissances, veille, plan
- **Date** : 2026-10-01
- **Contexte** : l'outil `podia_formation` produit la transcription de la formation Zonebourse dans
  `formation/` ; cette transcription est la matière première de l'aide à l'investissement.
- **Problème** : séparer l'outil et le projet de veille, ou les réunir ?
- **Décision** : les réunir. `formation/` reste ignoré par git (contenu propriétaire, régénérable) ; le
  dépôt porte le code, la méthode, les sources, les notes dérivées et le plan.
- **Alternatives rejetées** : deux dépôts (références croisées fragiles, deux installations).
- **Conséquences** : le dépôt doit rester **privé** ; la règle `formation.md` encadre les citations.

## DEC-003 — Outils `vigie` en bibliothèque standard, sur `podia_formation`
- **Date** : 2026-10-01
- **Contexte** : il faut transcrire des vidéos YouTube et collecter la presse sans alourdir l'installation Windows.
- **Décision** : paquet `vigie` (commandes `video`, `flux`, `sources`) qui réutilise yt-dlp, faster-whisper
  et les fonctions de `podia_formation` ; flux RSS lus avec `urllib` + `xml.etree`, sans dépendance nouvelle.
  Sous-titres fournis par la chaîne préférés à Whisper ; sous-titres automatiques seulement avec `--rapide`.
- **Alternatives rejetées** : `feedparser` (dépendance de plus pour un besoin simple) ; API YouTube (clé, quotas).
- **Conséquences** : les flux atypiques peuvent échouer (section « Flux en erreur » du digest) ; tests hors ligne obligatoires.

## DEC-004 — Charte d'analyse et auditeur
- **Date** : 2026-10-01
- **Contexte** : l'objectif est de se faire une opinion sur des faits et des précédents, pas sur des
  récits, et de ne pas prendre de décision financière sur une source unique.
- **Décision** : charte en dix points (`connaissances/methode/charte.md`) : faits datés et sourcés, trois
  sources indépendantes, séparation faits/analyses/opinions/inconnues, incertitude écrite, précédents,
  critères enquête contre complot, intérêts nommés, « et alors ? », pas d'ordre d'achat ou de vente,
  historique conservé. L'agent `auditeur` juge tout livrable qui touche au plan.
- **Conséquences** : les notes sont plus lentes à produire ; c'est voulu.

## DEC-005 — Sources en CSV, « orientation » comme repère
- **Date** : 2026-10-01
- **Contexte** : les sources doivent être éditables sans outil (Excel) et lisibles par le code.
- **Décision** : trois CSV (`medias`, `youtube`, `personnes`), séparateur « ; », colonne « orientation »
  (ligne éditoriale, propriétaire, financement) comme repère de lecture et non comme note de confiance ;
  flux RSS remplis de mémoire, à valider avec `vigie sources --tester`.
- **Conséquences** : la première veille commence par corriger les flux en erreur.
