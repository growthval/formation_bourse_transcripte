# Vigie — veille, investissement et anticipation

## WHY — Pourquoi ce projet existe
Se faire une opinion fondée sur des faits et des précédents, en croisant des sources de plusieurs pays,
pour investir en connaissance de cause et **anticiper** (marchés, géopolitique, droit international,
intelligence artificielle) sans se faire prendre de court : préparer un plan et un pivot, pas réagir.

## WHAT — Ce que fait le projet et comment il est organisé
Trois piliers dans un seul dépôt (privé) :
1. **La formation** Zonebourse « Investir en bourse », transcrite localement par l'outil `podia_formation`
   dans `formation/` (ignoré par git, propriété de Zonebourse) ; ses notes dérivées dans `connaissances/formation/`.
2. **La veille** : briefs recoupés, vidéos analysées, vérifications, dossiers de fond, dans `veille/`.
3. **Le plan** : scénarios probabilisés, signaux à seuils, pivot personnel, thèses, dans `plan/`.

Structure :
- `connaissances/methode/` — la méthode : `charte.md` (source unique des principes), `sources.md`
  (barème A à E), `grille-lecture.md` (le message derrière le message), `prevision.md` (anticiper).
- `connaissances/sources/` — registres CSV : `medias.csv`, `youtube.csv`, `personnes.csv`.
- `connaissances/formation/` — fiches par module, glossaire, synthèse de la méthode d'analyse enseignée.
- `veille/journal/` (briefs et digests), `veille/videos/` (une vidéo = un dossier : transcription + fiche),
  `veille/verifications/`, `veille/dossiers/` (IA, départs des labos, géopolitique, droit, marchés, `pays/`),
  `veille/a-traiter.md` (file d'attente).
- `plan/scenarios.md`, `plan/signaux.md`, `plan/pivot.md`, `plan/theses/`.
- `modeles/` — gabarits de toutes les notes. `docs/` — guides (outil de transcription).
- `podia_formation/` — outil de transcription de la formation. `vigie/` — outils de veille
  (`video`, `flux`, `sources`). `tests/` — tests hors ligne.

## HOW — Routage et conventions
**N'attends pas une commande** : si une demande correspond, invoque la skill toi-même.

| Demande | Skill |
|---|---|
| « quoi de neuf », « fais la veille », « point hebdo », chaque matin | `/veille` |
| une adresse YouTube, « analyse cette vidéo », « que vaut cette vidéo » | `/analyse-video` |
| « est-ce vrai que », « vérifie », « qu'en disent les autres pays » | `/croiser` |
| « creuse », « où en est le dossier », un pays, les départs des labos d'IA | `/dossier` |
| « que dit la formation », « fiche du module », « applique la méthode à X » | `/formation` |
| « revue du plan », « scénarios », « signaux », « pivot », « thèse sur X » | `/anticiper` |
| après une décision ou un apprentissage notable | `/log` |

- **Commandes** (racine du dépôt, environnement `.venv`) : tests `python -m pytest -q` ·
  transcription de la formation `formation audio "<adresse de leçon>"` puis `formation transcrire` ·
  vidéo `vigie video "<adresse>"` · presse `vigie flux --jours 2` · flux `vigie sources --tester`
  (sous macOS/Linux : `.venv/bin/python -m podia_formation …` et `.venv/bin/python -m vigie …`).
- **Langue** : tout en français (notes, code, messages). Phrases courtes, chiffres datés et sourcés.
- **Notes** : toujours depuis un modèle de `modeles/`, en-tête (date, auteur, confiance), quatre tas
  (faits / analyses / opinions / inconnues), section « Ce que ça change pour le plan », « Sources ».
  Détail dans `.claude/rules/veille.md`.
- **Dates** : utiliser la date du jour ; ne jamais antidater ni réécrire une prévision passée.

## RÈGLES — Ce qu'il ne faut JAMAIS faire
- Écrire un fait sans source datée, ou une conclusion sur une source unique (charte, points 1 et 2).
- Présenter une analyse, une opinion ou une hypothèse comme un fait ; employer un vocabulaire
  complotiste (« ils », « on nous cache ») ; faire une prévision sans horizon ni probabilité.
- Donner un ordre d'achat ou de vente, un conseil fiscal ou juridique : options et conséquences seulement.
- Modifier ou committer `formation/` ; copier une leçon entière hors de `formation/` ; rendre le dépôt public.
- Effacer l'historique d'un dossier, d'un scénario ou d'une prévision.
- Inventer le contenu d'une vidéo ou d'une leçon non transcrite.

## ARCHITECTURE — Décisions majeures
- Structure générée avec Structure Maker, tier Avancé allégé : agents + règles + skills + mémoire, sans
  orchestrateur ni hooks (DEC-001). Un seul dépôt, `formation/` hors git (DEC-002).
- `vigie` réutilise `podia_formation` (yt-dlp, faster-whisper) et la bibliothèque standard (DEC-003).
- La charte d'analyse est la source unique des principes ; l'auditeur juge ce qui touche au plan (DEC-004).

## Mémoire du projet
Index des décisions, apprentissages, blocages et de l'état courant (détail lu à la demande) :

@.claude/memory/MEMORY.md

**Discipline mémoire (fait partie de « terminé »)** : après une décision ou un changement notable,
enregistrer une entrée via `/log decision|learning|blocker|iteration "…"` et tenir `MEMORY.md` à jour.

## Agents disponibles
- `chercheur` : recherche multi-sources en lecture seule, synthèse sourcée.
- `analyste` : rédaction et mise à jour des notes au format des modèles.
- `auditeur` : verdict structuré sur une note (sourçage, rigueur, incertitude, utilité).
Les skills fixent l'ordre : recherche → rédaction → audit → propagation (signaux, backlog, mémoire).
Déléguer à l'agent dont la `description` correspond. Voir `.claude/agents/`.

## Règles ciblées
Chargées selon les fichiers touchés : `veille.md` (veille/, plan/), `code-python.md` (code et tests),
`formation.md` (contenus de la formation). Voir `.claude/rules/`.

## Gouvernance
Voix de l'assistant et modèle de l'utilisateur :

@.claude/governance/soul.md

@.claude/governance/user.md
