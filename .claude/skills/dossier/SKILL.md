---
name: dossier
description: Ouvre ou met à jour un dossier de fond dans veille/dossiers/ (IA et son avenir, départs des laboratoires d'IA, géopolitique, droit international, marchés, ou un pays) — état des lieux daté, acteurs et intérêts, précédents, scénarios, ce que ça change pour nous. À utiliser pour « où en est le dossier… », « creuse… », « fais le point sur… », « ajoute ça au dossier… ».
argument-hint: "[thème ou pays] [question ou fait à intégrer]"
allowed-tools: Read, Write, Edit, Glob, Grep, WebSearch, WebFetch, Agent
---

# /dossier — approfondir et tenir à jour

Demande : `$ARGUMENTS`

## 1. Trouver ou créer le dossier
- Thèmes : `veille/dossiers/ia-avenir-et-risques.md`, `ia-departs.md` (avec `ia-departs.csv`),
  `geopolitique.md`, `droit-international.md`, `marches.md`. Pays : `veille/dossiers/pays/<pays>.md`
  (voir `pays/README.md` pour la liste et le gabarit).
- Nouveau thème : créer le fichier à partir de `modeles/dossier.md` (nom en kebab-case, sans accent).
- Lire le dossier en entier avant d'écrire : la question centrale, l'état des lieux et le journal.

## 2. Rechercher ce qui manque (agents `chercheur`)
Formuler 2 à 4 questions précises (la question posée, plus ce que le dossier marque comme ouvert) et les
déléguer en parallèle à `chercheur` : faits datés, sources primaires, lectures de plusieurs pays,
précédents, et pour `ia-departs` : date, personne, poste, destination, raison déclarée, source.

## 3. Mettre à jour (agent `analyste`)
Déléguer à `analyste` : intégrer les faits nouveaux dans les sections du dossier (état des lieux, acteurs,
précédents, lectures divergentes, scénarios et indicateurs, ce que ça change), **ajouter une entrée datée
au journal**, ne rien effacer. Pour `ia-departs`, ajouter aussi une ligne au CSV. Les faits non sourcés
vont dans « Questions ouvertes ».

## 4. Auditer si le dossier touche au plan
Mise à jour importante (scénario modifié, signal déplacé, fait qui change une conclusion) → verdict de
`auditeur` noté dans le journal du dossier. Puis reporter dans `plan/scenarios.md` / `plan/signaux.md`.

## 5. Répondre
Cinq lignes : ce qui est nouveau, ce qui reste ouvert, le niveau de confiance, ce que ça change pour le
plan, le chemin du dossier.

## Garde-fous
- Un dossier est une mémoire datée : l'historique des mises à jour reste lisible.
- Acteurs et intérêts nommés, jamais « ils » ; précédents cherchés avant toute conclusion « inédite ».
