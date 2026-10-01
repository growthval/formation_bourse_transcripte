# Veille

Tout ce que le projet lit, vérifie et retient, daté et sourcé. Les principes sont dans
`connaissances/methode/charte.md`, la forme dans `.claude/rules/veille.md`.

| Dossier | Contenu | Produit par |
|---|---|---|
| `journal/` | `AAAA-MM-JJ-flux.md` (titres bruts des flux RSS) et `AAAA-MM-JJ.md` (brief recoupé) | `vigie flux`, `/veille` |
| `videos/` | un dossier par vidéo : `video.json`, `transcription.md/.txt/.srt`, `fiche.md` ; `index.md` les liste | `vigie video`, `/analyse-video` |
| `verifications/` | une note par affirmation vérifiée, avec verdict | `/croiser` |
| `dossiers/` | dossiers de fond thématiques et par pays, à historique | `/dossier` |
| `a-traiter.md` | file d'attente : vidéos, documents, questions à creuser | tout le monde |

Les fichiers audio (`videos/*/audio.m4a`) ne sont pas commités (volumineux, régénérables).

## Rythme conseillé
- Souvent : `/veille` (2 jours) ; le lundi : `/veille semaine`.
- À chaque vidéo marquante : `vigie video "<adresse>"` puis `/analyse-video`.
- Chaque semaine : vider `a-traiter.md` avec `/croiser` et `/dossier`.
- Chaque mois : `/anticiper revue`.
