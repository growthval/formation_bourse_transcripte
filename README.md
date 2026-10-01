# Vigie — investir, s'informer, anticiper

Projet personnel en trois piliers, piloté dans **Claude Code** :

1. **La formation** « Investir en bourse » de Zonebourse, transcrite intégralement sur votre machine par
   l'outil `podia_formation` (voir [`docs/outil-transcription.md`](docs/outil-transcription.md)), puis
   exploitée en fiches, glossaire et synthèse de méthode.
2. **La veille** : chaque jour, ce que disent les grands médias français, européens, américains et des
   autres pays, les institutions, les chaînes YouTube légitimes, recoupé par zone et audité ; les vidéos
   importantes transcrites et analysées (le message réel derrière le message) ; les affirmations
   vérifiées ; des dossiers de fond (IA et ses dangers, départs des laboratoires d'IA, géopolitique, droit
   international, marchés, pays).
3. **Le plan** : des scénarios 2026-2030 probabilisés, une table de signaux à seuils, un plan de pivot
   « si X alors Y », des thèses d'investissement rédigées à froid.

Le fil conducteur est une [charte d'analyse](connaissances/methode/charte.md) : des faits datés et
sourcés, au moins trois sources indépendantes, les précédents avant les récits, enquête et non théorie du
complot, l'incertitude écrite, et jamais d'ordre d'achat ou de vente : des options et leurs conséquences.

> Dépôt **privé** : les notes dérivent d'une formation payante. Le dossier `formation/` (transcriptions)
> n'est jamais commité.

## Démarrage rapide

1. **Récupérer le projet** sur le disque `E:`, dans un dossier court et hors OneDrive :
   ```bat
   git clone -b claude/eager-goodall-bdijp5 https://github.com/growthval/formation_bourse_transcripte E:\vigie
   ```
   (ou bouton « Code → Download ZIP », puis copier le contenu dans `E:\vigie`). Le nom du dossier est libre.
   **Si l'outil de transcription est déjà installé** (dossier avec `.venv\` et `formation\` transcrit, par
   exemple `E:\formation` issu d'un ZIP) : ne rien recopier ni réinstaller, rattacher ce dossier au dépôt :
   ```bat
   cd /d E:\formation
   git init
   git remote add origin https://github.com/growthval/formation_bourse_transcripte
   git fetch origin claude/eager-goodall-bdijp5
   git checkout -f -B claude/eager-goodall-bdijp5 origin/claude/eager-goodall-bdijp5
   ```
   Les fichiers de l'outil sont remplacés par ceux du dépôt ; `formation\` et `.venv\` sont conservés
   (ignorés par git). Dossier déjà cloné : `git fetch origin` puis `git checkout claude/eager-goodall-bdijp5` suffisent.
2. **Installer** (Windows) : double-clic sur `installer_windows.bat` (Python 3.12, environnement, bibliothèques,
   CUDA si carte NVIDIA). macOS/Linux : voir le guide de l'outil.
3. **Transcrire la formation** (une fois, plusieurs heures) :
   ```bat
   formation connexion "https://zonebourse.podia.com/p/courses/investir-en-bourse/<module>/<leçon>"
   formation audio "<la même adresse>"
   formation transcrire
   ```
   Détail et dépannage : [`docs/outil-transcription.md`](docs/outil-transcription.md).
4. **Vérifier les flux de presse** : `vigie sources --tester`, puis corriger les adresses en erreur dans
   `connaissances/sources/medias.csv`. Puis `vigie chaines` pour suivre les vidéos des chaînes de `youtube.csv`.
5. **Ouvrir Claude Code** à la racine du dépôt et accepter le dialogue de confiance. Il lit `CLAUDE.md`,
   charge la mémoire et les commandes. Première session conseillée :
   `/formation synthèse` → `/veille` → `/analyse-video "<adresse de la vidéo Finary>"` → `/anticiper revue`.

## Les commandes dans Claude Code

| Commande | Ce qu'elle fait | Produit |
|---|---|---|
| `/veille [jours \| semaine] [thème]` | Digest des flux, recherche par zone (6 agents en parallèle), brief recoupé, audité | `veille/journal/AAAA-MM-JJ.md` |
| `/analyse-video <adresse \| dossier>` | Transcription, grille de lecture, vérification des affirmations clés, fiche | `veille/videos/<dossier>/fiche.md` |
| `/croiser "affirmation"` | Trois sources indépendantes, la primaire d'abord, verdict et confiance | `veille/verifications/…` |
| `/dossier <thème \| pays> [question]` | Dossier de fond à historique : état des lieux, acteurs, précédents, scénarios | `veille/dossiers/…` |
| `/formation <question \| module N \| synthèse \| appliquer à X>` | Exploite la transcription : fiches, glossaire, méthode, thèses | `connaissances/formation/…`, `plan/theses/` |
| `/anticiper [revue \| scénario \| signaux \| pivot \| thèse]` | Revue mensuelle, scénarios, signaux, pivot | `plan/…` |
| `/log <type> "résumé"` | Mémoire du projet (décisions, apprentissages, blocages) | `.claude/memory/` |

Il n'est pas nécessaire de taper les commandes : une demande en français (« quoi de neuf ? », une adresse
YouTube collée, « est-ce vrai que… ») est routée vers la bonne commande (voir `CLAUDE.md`).

Trois agents travaillent derrière ces commandes : `chercheur` (recherche multi-sources, lecture seule),
`analyste` (rédaction au format des modèles), `auditeur` (verdict structuré avant qu'une note compte).

## Les outils en ligne de commande

| Commande | Rôle |
|---|---|
| `formation …` | Inventaire, audio, transcription Whisper et planning de la formation Podia ([guide](docs/outil-transcription.md)) |
| `vigie video "<adresse>"` | Récupère la transcription d'une vidéo YouTube en quelques secondes : sous-titres de la chaîne s'ils existent, sinon les sous-titres automatiques (la « Transcription » du site), sans télécharger la vidéo ; prépare `fiche.md`. `--whisper` : audio + Whisper, plus fidèle mais long (`--modele large-v3-turbo` pour accélérer) |
| `vigie chercher <mots-clés> [--nombre 10]` | Cherche des vidéos YouTube par mots-clés (sans clé d'API) et enregistre la liste dans `veille/videos/recherches/` |
| `vigie chaines` | Retrouve l'identifiant des chaînes de `youtube.csv` : leurs nouvelles vidéos entrent ensuite dans le digest |
| `vigie flux --jours 2 [--filtre ia,taïwan]` | Digest Markdown des derniers articles des sources (flux RSS), des nouvelles vidéos des chaînes suivies et des vidéos citées dans les articles, dans `veille/journal/` |
| `vigie sources --tester` | Vérifie les registres et interroge chaque flux (médias et chaînes) ; signale les flux figés |

Sous macOS/Linux : `.venv/bin/python -m podia_formation …` et `.venv/bin/python -m vigie …`.
YouTube demande un moteur JavaScript pour yt-dlp : `winget install DenoLand.Deno` (Windows) ou Deno/Node sur les autres systèmes.

## Arborescence

```
CLAUDE.md                 constitution lue par Claude Code (mission, routage, règles, mémoire)
.claude/                  agents, règles ciblées, skills (commandes), mémoire, gouvernance, settings
connaissances/
  methode/                charte, barème des sources, grille de lecture, méthode de prévision
  sources/                medias.csv, youtube.csv, personnes.csv (séparateur « ; », Excel)
  formation/              fiches par module, glossaire, synthèse de méthode (notes dérivées)
veille/
  journal/                digests de flux et briefs datés
  videos/                 un dossier par vidéo : transcription + fiche ; index.md
  verifications/          notes de vérification
  dossiers/               IA, départs des labos (+ CSV), géopolitique, droit international, marchés, pays/
  a-traiter.md            file d'attente
plan/                     scenarios.md, signaux.md, pivot.md, theses/
modeles/                  gabarits de toutes les notes
docs/                     guide de l'outil de transcription
podia_formation/          outil de transcription (Podia → audio → Whisper → planning)
vigie/                    outils de veille (video, flux, sources)
tests/                    tests hors ligne (pytest)
formation/                (créé par l'outil, ignoré par git) transcriptions, textes, PDF, planning
```

## Méthode en bref

- [Charte d'analyse](connaissances/methode/charte.md) : dix principes, source unique.
- [Évaluer une source](connaissances/methode/sources.md) : barème A (primaire) à E (invérifiable), signaux d'alerte.
- [Grille de lecture](connaissances/methode/grille-lecture.md) : extraire la thèse, les preuves, les omissions, les intérêts, le message réel.
- [Anticiper sans deviner](connaissances/methode/prevision.md) : taux de base, prévisions falsifiables, scénarios, signaux, revue.

## Développement

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```
Les tests n'utilisent pas le réseau. Conventions : `.claude/rules/code-python.md`.

## Gouvernance Claude Code

La structure (`CLAUDE.md`, `.claude/`) a été générée avec le moteur
[Structure Maker](https://github.com/growthval/structure-maker) (tier Avancé allégé : agents, règles,
skills, mémoire, soul/user ; sans orchestrateur ni hooks). Provenance et composants :
[`.claude/manifest.yaml`](.claude/manifest.yaml) ; décisions tracées dans
[`.claude/memory/DECISIONS.md`](.claude/memory/DECISIONS.md).
