# Registre des sources

Trois fichiers CSV (séparateur « ; », s'ouvrent dans Excel) lus par les outils et par les commandes Claude Code :

| Fichier | Contenu | Utilisé par |
|---|---|---|
| `medias.csv` | Presse, institutions, think tanks, blogs IA, avec leur flux RSS | `vigie flux`, `/veille`, `/croiser` |
| `youtube.csv` | Chaînes YouTube et leur type (info, explicatif, entretien, institutionnel, opinion) | `/veille`, `/analyse-video` |
| `personnes.csv` | Personnes à suivre (départs des laboratoires d'IA, chercheurs, journalistes, analystes) | `/dossier ia-departs`, `/veille` |

## Règles d'usage

- **Jamais une source seule.** Un fait n'entre dans une note qu'avec au moins trois sources indépendantes
  (pays, orientation ou type différents), dont une primaire quand elle existe. Barème dans
  [`../methode/sources.md`](../methode/sources.md).
- **La colonne « orientation » est un repère de lecture**, pas une note de confiance : elle rappelle la
  ligne éditoriale, le propriétaire ou le financement, pour équilibrer les angles. Corrigez-la si elle
  vous paraît inexacte.
- **Les médias d'État** (TASS, Xinhua, CGTN, Al Jazeera pour le Golfe) servent à connaître la position
  officielle d'un pays. On les cite comme telles, jamais comme établissant un fait.
- **Les chaînes « opinion »** et les comptes X/Twitter sont des sources de niveau D : utiles pour détecter
  un signal ou un argument, jamais pour l'établir.

## Vérifier les flux RSS

Les adresses RSS ont été remplies de mémoire et n'ont pas pu être testées depuis la session qui a créé
le projet (accès réseau bloqué). Avant la première veille :

```bat
vigie sources --tester
```

Pour chaque flux en erreur : chercher « RSS » sur le site du média, corriger l'adresse dans
`medias.csv`, ou laisser vide (la source est alors consultée à la main par `/veille`).

Une case ne doit jamais contenir de « ; » (c'est le séparateur) : la ligne serait décalée et la source
désactivée. `vigie sources` signale les lignes mal formées.

## Ajouter une source

1. Vérifier qu'elle passe la grille de [`../methode/sources.md`](../methode/sources.md) (identité réelle,
   méthode visible, corrections publiées, intérêts déclarés).
2. Ajouter une ligne dans le bon fichier, remplir « orientation » et « notes » (ce qui doit rester en tête en la lisant).
3. Relancer `vigie sources --tester` si un flux RSS a été ajouté.

## Chaînes YouTube : nouvelles vidéos dans le digest

YouTube publie pour chaque chaîne un flux de ses dernières vidéos, sans clé d'API. Il faut l'identifiant
de la chaîne (« UC… »), que `vigie chaines` retrouve à partir de l'adresse et écrit dans la colonne
`id_chaine` de `youtube.csv`. Ensuite, `vigie flux` ajoute une section « Nouvelles vidéos des chaînes
suivies » au digest, et `/veille` les voit. Après avoir ajouté une chaîne : relancer `vigie chaines`.
Si l'adresse d'une chaîne est inconnue ou fausse, laissez la case vide : la commande retrouve la chaîne par
son nom (recherche YouTube) et écrit l'adresse ; une correspondance partielle est signalée, à vérifier.

Pour chercher des vidéos par mots-clés : `vigie chercher ia 2027 emploi --nombre 15` (liste enregistrée
dans `veille/videos/recherches/`). Les vidéos citées par les articles du digest sont listées dans la
section « Vidéos citées dans les articles ».
