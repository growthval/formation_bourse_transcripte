---
name: analyse-video
description: Analyse une vidéo (YouTube ou autre) à partir de sa transcription — thèse, arguments, affirmations à vérifier, intérêts de l'auteur, message réel, conséquences pour le plan. À utiliser pour « analyse cette vidéo », « que vaut cette vidéo ? », une adresse YouTube collée, ou un dossier de veille/videos/. Remplit la fiche.md du dossier de la vidéo.
argument-hint: "[adresse YouTube | nom du dossier dans veille/videos | titre]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, WebSearch, WebFetch, Agent
---

# /analyse-video — le message derrière le message

Cible : `$ARGUMENTS`

## 1. Obtenir la transcription
- **Adresse web** : lancer `.venv/Scripts/python -m vigie video "<adresse>"` (Windows) ou
  `.venv/bin/python -m vigie video "<adresse>"` (macOS/Linux). L'outil prend les sous-titres fournis par
  la chaîne s'il y en a, sinon télécharge l'audio et transcrit avec Whisper (long : prévenir l'utilisateur,
  proposer `--rapide` pour les sous-titres automatiques si la vidéo est longue et le sujet peu technique).
  Si YouTube réclame un moteur JavaScript, suivre le message de l'outil (Deno) et relancer.
- **Dossier ou titre** : le retrouver dans `veille/videos/index.md` ou par `Glob` sur `veille/videos/*`.
- Lire `veille/videos/<dossier>/transcription.md` (horodatages) et `video.json` (chaîne, date, chapitres).

## 2. Lire avec la grille
Appliquer `connaissances/methode/grille-lecture.md`, point par point : thèse en une phrase, arguments et
preuves (avec horodatage), affirmations vérifiables, omissions, intérêts de l'auteur (regarder la fiche de
la chaîne dans `connaissances/sources/youtube.csv` ; ce qu'elle vend), registre, nouveau ou connu (comparer
aux dossiers de `veille/dossiers/`), message réel, test de réfutation.

## 3. Vérifier ce qui porte la thèse
Pour les 3 à 5 affirmations décisives, déléguer à `chercheur` (une délégation par affirmation, en
parallèle) : « vérifier avec au moins trois sources indépendantes, la primaire d'abord ». Verdict par
affirmation : confirmé / partiellement / non confirmé / faux / indéterminé. Si une vérification est
lourde, créer une note avec `/croiser` et la lier.

## 4. Rédiger la fiche
Remplir `veille/videos/<dossier>/fiche.md` (déjà pré-remplie par l'outil ; sinon partir de
`modeles/fiche-video.md`), via `analyste` pour une vidéo longue ou importante. Niveau de confiance,
date de rédaction, sources. Dans `veille/videos/index.md`, passer la ligne de la vidéo à « analysée ».

## 5. Auditer et propager
- Vidéo qui touche au plan (IA, marchés, géopolitique majeure) → verdict de `auditeur` noté dans la fiche.
- Faits nouveaux → dossier concerné (`/dossier`), signaux → `plan/signaux.md`, questions → `veille/a-traiter.md`.
- Répondre à l'utilisateur en six lignes : thèse, ce qui est étayé, ce qui ne l'est pas, message réel,
  ce que ça change, chemin de la fiche.

## Garde-fous
- La transcription est la source ; ne pas « deviner » le contenu d'une vidéo non transcrite.
- Les sous-titres automatiques contiennent des erreurs de noms et de chiffres : vérifier avant de citer.
- Pas d'ordre d'achat ou de vente dans la fiche (charte, point 9).
