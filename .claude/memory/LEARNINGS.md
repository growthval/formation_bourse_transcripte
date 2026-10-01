<!-- Registre des apprentissages. Reporter dans MEMORY.md. -->
# Apprentissages — Vigie

## LRN-001 — Session cloud : pas de YouTube ni de flux RSS
- **Date** : 2026-10-01
- **Découverte** : depuis la session Claude Code sur le web qui a créé le projet, youtube.com et tous les
  flux RSS testés étaient bloqués par le proxy réseau.
- **Impact** : les adresses RSS n'ont pas pu être validées ; `vigie sources --tester` doit être lancé en
  local avant la première veille. Les vidéos se transcrivent en local.
- **Source** : essais `curl` sur 45 flux (code 000) et WebFetch sur youtube.com (EGRESS_BLOCKED).

## LRN-002 — yt-dlp et YouTube : moteur JavaScript requis
- **Date** : 2026-10-01
- **Découverte** : yt-dlp a besoin d'un moteur JavaScript (Deno conseillé) pour résoudre les signatures
  YouTube ; sans lui, le téléchargement échoue avec un message sur le « n challenge » ou le « JS runtime ».
- **Impact** : `winget install DenoLand.Deno` (Windows) documenté dans le README et dans le message
  d'erreur de `vigie video`.
- **Source** : documentation yt-dlp, README de l'outil de transcription.

## LRN-003 — ElementTree : le joker `{*}` ne marche pas avec `iter()`
- **Date** : 2026-10-01
- **Découverte** : `root.iter("{*}item")` ne renvoie rien ; le joker d'espace de noms n'est pris en charge
  que par `find`, `findall` et `iterfind` (chemins XPath).
- **Impact** : `vigie/flux.py` utilise `root.iterfind(".//{*}item")` ; un test couvre RSS 2.0, RSS 1.0 et Atom.
- **Source** : échec de test puis correction.

## LRN-004 — Un « ; » dans une note du registre décale la ligne
- **Date** : 2026-10-01
- **Découverte** : les CSV du registre utilisent « ; » comme séparateur ; une note contenant « ; » ajoute
  une colonne, la valeur « oui » glisse hors de la colonne « actif » et la source est désactivée sans erreur.
- **Impact** : `vigie sources` signale désormais les lignes mal formées ; consigne ajoutée en tête des CSV.
- **Source** : deux sources (ECFR, Times of Israel) devenues inactives après l'ajout d'une note.
