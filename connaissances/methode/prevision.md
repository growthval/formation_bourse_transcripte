# Anticiper sans deviner

Méthode pour `plan/` (scénarios, signaux, pivot) et pour les sections « Ce que ça change » des notes.
Elle emprunte aux prévisionnistes calibrés (Tetlock, « Superforecasting »), à la planification par
scénarios (méthode Shell) et à l'analyse des précédents.

## 1. Partir du taux de base
Avant de juger une situation, chercher la classe de référence : combien de fois un événement comparable
s'est produit, en combien de temps, avec quelles conséquences. Exemples de classes :
- bulles technologiques (chemins de fer, électricité, radio, internet 2000, télécoms) : combien ont fini en
  krach, combien ont laissé une infrastructure durable, quels investisseurs ont gagné (rarement les
  premiers) ;
- vagues d'automatisation (tracteurs, distributeurs de billets, tableurs, robots industriels) : rythme réel
  de disparition des emplois contre rythme annoncé ;
- crises de dette souveraine, chocs pétroliers (1973, 1979), pandémies, guerres régionales : effets sur
  l'inflation, les taux, les actions, dans les 12 à 36 mois.
Puis ajuster pour ce qui est réellement différent cette fois, en le nommant.

## 2. Écrire des prévisions falsifiables
Une prévision = un événement précis + un horizon + une probabilité. « L'IA va bouleverser l'emploi » n'est
pas vérifiable. « Le taux de chômage des 25-34 ans diplômés en France dépasse 10 % avant fin 2027 : 20 % »
l'est. Tenir le registre dans `plan/scenarios.md` et le relire : la calibration s'apprend en se comparant
à ses propres prévisions passées.

## 3. Raisonner par scénarios, pas par certitude
Trois à quatre scénarios contrastés, chacun avec :
- ses hypothèses (ce qui doit être vrai pour qu'il se réalise) ;
- ses précédents ;
- sa probabilité subjective (la somme fait 100 %) ;
- ses indicateurs avancés (ce qu'on verrait en premier s'il se réalisait) ;
- ses conséquences (emploi, revenus, marchés, inflation, géopolitique) ;
- les actions qui restent bonnes dans la plupart des scénarios (robustes) et celles qui ne valent que dans
  un seul (paris).

## 4. Surveiller des signaux, pas des opinions
`plan/signaux.md` tient une table d'indicateurs avec un seuil et une source. Un signal est bon s'il est
mesurable, publié régulièrement et difficile à manipuler (données officielles, prix de marché, décisions
effectives). Les opinions d'experts sont un signal faible ; leur convergence soudaine en est un plus fort.

## 5. Mettre à jour, un peu, souvent
Chaque brief ou dossier qui apporte un fait nouveau déplace légèrement les probabilités (raisonnement
bayésien : un fait compatible avec plusieurs scénarios ne prouve pas grand-chose). Éviter les deux excès :
ne jamais bouger, ou tout réécrire à chaque gros titre.

## 6. Pré-mortem
Pour chaque décision du plan, imaginer qu'elle a échoué dans deux ans et écrire pourquoi. Les raisons
trouvées deviennent des signaux à surveiller ou des conditions à poser.

## 7. Pièges à nommer dans les notes
- Récit séduisant (narrative fallacy) : une histoire cohérente n'est pas une preuve.
- Biais de récence : le dernier événement paraît le plus important.
- Biais de confirmation : chercher ce qui confirme. Contre-mesure : la source qui contredit (charte, point 2).
- Catastrophisme et optimisme comme produits : les deux se vendent bien.
- Horizon confondu : ce qui est probable à dix ans ne l'est pas forcément à dix-huit mois, et inversement.

## 8. Rythme
- Quotidien ou presque : `/veille` (faits et signaux).
- Hebdomadaire : relecture des signaux, mise à jour des dossiers touchés.
- Mensuel : `/anticiper revue` (probabilités des scénarios, actions du pivot, prévisions à évaluer).
- Annuel : relecture des prévisions passées, score de calibration, révision des scénarios.
