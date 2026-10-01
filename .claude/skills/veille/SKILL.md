---
name: veille
description: Brief de veille du jour ou de la semaine — presse de plusieurs pays, institutions, IA, marchés — recoupé par zone et audité. À utiliser pour « quoi de neuf ? », « fais la veille », « résume l'actualité », « point hebdo », ou chaque matin. Produit veille/journal/AAAA-MM-JJ.md.
argument-hint: "[jours | semaine] [thème facultatif]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, WebSearch, WebFetch, Agent
---

# /veille — brief recoupé

Demande reçue : `$ARGUMENTS` (vide = 2 derniers jours ; `semaine` = 7 jours, plus synthétique ;
un nombre = période en jours ; un thème restreint les zones, ex. `/veille 3 IA`).

## 1. Collecter les titres
1. Lancer le digest des flux (depuis la racine du dépôt) :
   `.venv/Scripts/python -m vigie flux --jours N` (Windows) ou `.venv/bin/python -m vigie flux --jours N`
   (macOS/Linux) ; sans environnement, `python -m vigie flux --jours N`. Avec un thème : `--filtre mot1,mot2`.
2. Lire `veille/journal/AAAA-MM-JJ-flux.md`. Les flux en erreur ne bloquent pas : les sources concernées
   sont couvertes par la recherche web de l'étape 2. Signaler les erreurs répétées à la fin (adresse à
   corriger dans `connaissances/sources/medias.csv`).

## 2. Rechercher par zone (en parallèle, agents `chercheur`)
Lancer un agent `chercheur` par zone, en parallèle (les zones sont indépendantes), avec pour consigne :
« Pour la période du … au …, les 3 à 5 faits qui comptent dans cette zone, chacun avec au moins deux
sources de pays ou de lignes éditoriales différents, les divergences de lecture, et un signal faible.
Partir du digest `veille/journal/AAAA-MM-JJ-flux.md`. Format de sortie de ton agent. »
Zones (toutes par défaut, restreintes par le thème s'il y en a un) :
- France et Europe (politique, économie, UE, défense) ;
- États-Unis et Amériques ;
- Asie : Chine, Japon, Inde, Taïwan, Corée ;
- Moyen-Orient, Russie et Ukraine, Afrique ;
- Marchés et banques centrales (taux, inflation, indices, crédit, matières premières) ;
- Intelligence artificielle (laboratoires, capacités, régulation, départs et prises de position, économie du secteur).

## 3. Rédiger (agent `analyste`)
Déléguer la rédaction à `analyste` avec les six synthèses, le modèle `modeles/brief.md`, la cible
`veille/journal/AAAA-MM-JJ.md` (ou `AAAA-MM-JJ-semaine.md`) et la consigne : relire `plan/signaux.md` et
`plan/scenarios.md` pour remplir « Ce que ça change pour le plan ». Pour un brief très court (une zone,
un jour), rédiger soi-même avec le même modèle.

## 4. Auditer (agent `auditeur`)
Déléguer le brief à `auditeur`. Si AJUSTÉ : appliquer les corrections (soi-même ou via `analyste`) et
noter le verdict final dans l'en-tête. Si REJETÉ : reprendre à l'étape 2 sur les points en cause.

## 5. Propager
- `plan/signaux.md` : mettre à jour « état actuel » et « dernier contrôle » des indicateurs touchés.
- `veille/a-traiter.md` : ajouter ce qui mérite `/croiser` ou `/dossier`.
- `/log iteration "veille du …"` si quelque chose de notable a été décidé ou appris.
- Terminer par le résumé « En une minute » du brief et le chemin du fichier.

## Garde-fous
- Jamais un fait sur une source unique ; jamais d'ordre d'achat ou de vente (charte, points 2 et 9).
- Ne pas narrer la collecte : le brief contient des faits, des sources et des conséquences.
