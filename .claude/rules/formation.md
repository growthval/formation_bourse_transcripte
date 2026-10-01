---
paths:
  - "formation/**"
  - "connaissances/formation/**"
---
# Contenus de la formation Zonebourse

- `formation/` est la **sortie de l'outil** (transcriptions, textes, PDF) : lecture seule, jamais commité,
  régénéré par `formation audio` / `formation transcrire`. Pour corriger une transcription, relancer
  l'outil (`--forcer`, `--modele francais`, `--vocabulaire`), pas l'éditer.
- Les contenus appartiennent à **Zonebourse** : usage personnel. Dans les notes du projet, on **cite**
  (« Module 3, leçon 2, 12:40 ») et on **reformule** ; citations courtes seulement, jamais une leçon
  entière copiée hors de `formation/`. Le dépôt reste privé.
- Les notes dérivées vont dans `connaissances/formation/` (fiches par module, glossaire, synthèse de méthode)
  et portent la référence de la leçon source.
- Quand une note de veille évalue une société, un secteur ou un ETF, elle applique la méthode de la
  formation (`connaissances/formation/methode-zonebourse.md` ; si ce fichier n'existe pas encore, lancer
  `/formation synthèse` d'abord) et le dit.
