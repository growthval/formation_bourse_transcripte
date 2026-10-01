# Signaux surveillés

Table des indicateurs qui font bouger les scénarios et déclenchent les actions du pivot. Un bon signal
est mesurable, publié régulièrement par une source A ou B, et difficile à manipuler. « État actuel » et
« dernier contrôle » sont mis à jour par `/veille` et `/anticiper revue` ; on ne modifie jamais un seuil sans
une ligne au journal.

| Indicateur | Source | Seuil d'alerte | Scénarios | État actuel | Dernier contrôle |
|---|---|---|---|---|---|
| Taux directeur de la Fed et projections | federalreserve.gov | changement de direction | A, B, D | à renseigner | — |
| Taux directeur de la BCE | ecb.europa.eu | changement de direction | B, D | à renseigner | — |
| Courbe des taux américaine (10 ans moins 3 mois) | FRED (T10Y3M) | négative puis repentification rapide | B | à renseigner | — |
| Inflation sous-jacente (États-Unis, zone euro) | BLS, Eurostat | > 4 % ou < 1 % sur 3 mois | C, D | à renseigner | — |
| Taux de chômage américain | BLS | hausse de 0,5 point sur 12 mois (règle de Sahm) | B | à renseigner | — |
| Emploi des jeunes diplômés (États-Unis, France) | BLS, INSEE | hausse nette du chômage de la tranche 22-27 ans | A, B | à renseigner | — |
| Spreads de crédit à haut rendement (États-Unis) | FRED (BAMLH0A0HYM2) | > 500 points de base | B, C | à renseigner | — |
| VIX | CBOE | > 30 pendant plus d'une semaine | B, C | à renseigner | — |
| Poids des 10 premières capitalisations dans le S&P 500 | S&P, Bloomberg | record historique puis recul de 5 points | A, B | à renseigner | — |
| Dépenses d'investissement des hyperscalers (trimestre) | rapports trimestriels (SEC) | révision à la baisse par deux acteurs | A, B | à renseigner | — |
| Revenus IA publiés par les laboratoires | presse B, rapports | croissance annuelle < 50 % | A, B | à renseigner | — |
| Horizon temporel des tâches réalisables par les agents | METR | doublement en moins de 6 mois / stagnation 12 mois | A, B | à renseigner | — |
| Départs publics de laboratoires d'IA motivés par la sécurité (12 mois) | `veille/dossiers/ia-departs.csv` | 3 départs sourcés avec déclarations convergentes | A | à renseigner | — |
| Étapes d'application de l'AI Act | Commission européenne | chaque date d'entrée en vigueur | D | à renseigner | — |
| Prix du Brent | ICE, Bloomberg | > 100 $ ou < 50 $ | C | à renseigner | — |
| Prix du gaz européen (TTF) | ICE | > 60 €/MWh | C | à renseigner | — |
| Taux de fret conteneurs (Drewry WCI) | Drewry | doublement en 3 mois | C | à renseigner | — |
| Activité militaire autour de Taïwan | ministère de la Défense de Taïwan (bulletins quotidiens) | blocus, exercices avec tirs réels prolongés | C | à renseigner | — |
| Sanctions nouvelles (UE, OFAC) visant un secteur de notre portefeuille | sites officiels | toute mesure | C, D | à renseigner | — |
| Dépenses militaires mondiales | SIPRI (annuel) | hausse > 10 % | C, D | à renseigner | — |
| Dette publique française et charge d'intérêt, notation | INSEE, agences | dégradation de note, charge > 3 % du PIB | D | à renseigner | — |
| Cours de l'or et du dollar (DXY) | Bloomberg | or +20 % sur 6 mois ; DXY ± 10 % | C | à renseigner | — |

## Journal des seuils
- 2026-10-01 : table initiale ; seuils indicatifs à confirmer lors de la première revue.
