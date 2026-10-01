---
paths:
  - "veille/**"
  - "plan/**"
---
# Écrire une note de veille ou de plan

Ces règles se chargent quand on touche `veille/` ou `plan/`. Les principes sont dans
`connaissances/methode/charte.md` ; ici, leur forme concrète.

- **Modèle** : partir du gabarit de `modeles/` ; aucun champ de gabarit non rempli (double accolade) ne reste dans une note finie.
- **En-tête** : date, auteur (agent ou humain), niveau de confiance (faible / moyen / élevé), et pour les
  notes importantes : verdict de l'auditeur.
- **Noms de fichiers** : `AAAA-MM-JJ.md` (brief), `AAAA-MM-JJ-<sujet>.md` (vérification), kebab-case sans
  accent pour les dossiers (`droit-international.md`, `pays/etats-unis.md`).
- **Principes** : charte, points 1 à 4 (faits sourcés et datés, trois sources, quatre tas, incertitude),
  6 (vocabulaire : acteurs nommés, pas de « on nous cache »), 9 et 10 ; niveau des sources selon
  `connaissances/methode/sources.md`. Un chiffre sans source va dans « à vérifier ».
- **Historique** : dans un dossier ou un scénario, on ajoute une entrée datée au journal, on n'efface pas.
- **Fin de note** : section « Ce que ça change pour le plan » (scénario, signal, option), puis « Sources ».
- **Liens internes** : renvoyer aux dossiers (`veille/dossiers/`), aux scénarios (`plan/scenarios.md`) et
  aux signaux (`plan/signaux.md`) plutôt que de recopier leur contenu.
