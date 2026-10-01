---
name: anticiper
description: Tient le plan d'anticipation — scénarios 2026-2030 avec probabilités, table des signaux à seuils, plan de pivot personnel (si X alors Y), thèses d'investissement — et sa revue mensuelle. À utiliser pour « revue du plan », « où en sont les scénarios ? », « ajoute un signal », « mon plan de pivot », « thèse sur… ».
argument-hint: "[revue | scénario <nom> | signaux | pivot | thèse <sujet>]"
allowed-tools: Read, Write, Edit, Glob, Grep, WebSearch, WebFetch, Agent
---

# /anticiper — scénarios, signaux, pivot : décider à froid

Demande : `$ARGUMENTS` (vide = `revue`). Méthode : `connaissances/methode/prevision.md`.

## revue (mensuelle)
1. Lire `plan/scenarios.md`, `plan/signaux.md`, `plan/pivot.md`, les briefs du mois
   (`veille/journal/`) et les journaux des dossiers mis à jour.
2. Pour chaque signal : état actuel (déléguer à `chercheur` les valeurs à rafraîchir, sources A/B),
   seuil franchi ou non, date de contrôle.
3. Pour chaque scénario : hypothèses confirmées ou infirmées ce mois, probabilité révisée (la somme fait
   100 %), avec une ligne de justification datée dans son journal.
4. Pour le pivot : déclencheurs atteints ? actions à lancer, à préparer, à abandonner.
5. Prévisions arrivées à échéance : notées justes ou fausses, sans les réécrire.
6. `auditeur` sur les fichiers modifiés ; `/log decision` pour tout changement de cap.
7. Répondre : ce qui a bougé, ce qui n'a pas bougé, les trois actions du mois.

## scénario <nom>
Créer ou mettre à jour une section de `plan/scenarios.md` avec `modeles/scenario.md` : hypothèses,
précédents (déléguer à `chercheur` la recherche historique), probabilité, indicateurs avancés (ajoutés à
`plan/signaux.md`), conséquences, actions robustes / paris, ce qui l'invaliderait.

## signaux
Ajouter ou modifier des lignes de `plan/signaux.md` : indicateur mesurable, source publique régulière,
seuil, scénario concerné. Rafraîchir les valeurs sur demande.

## pivot
Mettre à jour `plan/pivot.md` : objectifs, déclencheurs « si X alors Y », compétences, finances
(principes de la formation : épargne de précaution, diversification, horizon), revue des actions. Les
décisions restent celles de l'utilisateur ; le document présente des options et leurs conséquences.

## thèse <sujet>
Voir `/formation appliquer à <sujet>` : thèse rédigée avec `modeles/these.md` dans `plan/theses/`.

## Garde-fous
- Toute prévision a un horizon et une probabilité ; une prévision passée ne se réécrit pas.
- Pas d'ordre d'achat ou de vente ; pas de conseil fiscal ou juridique (renvoyer à un professionnel).
