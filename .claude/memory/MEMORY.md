# Mémoire — Vigie

## Décisions récentes
- [DEC-001](./DECISIONS.md#dec-001) : structure générée avec Structure Maker, tier Avancé allégé (sans orchestrateur ni hooks) (2026-10-01)
- [DEC-002](./DECISIONS.md#dec-002) : un seul dépôt pour l'outil de transcription, la base de connaissances, la veille et le plan (2026-10-01)
- [DEC-003](./DECISIONS.md#dec-003) : outils de veille `vigie` en Python standard, réutilisant `podia_formation` (2026-10-01)
- [DEC-004](./DECISIONS.md#dec-004) : charte d'analyse (faits, trois sources, précédents, pas de complotisme) et auditeur obligatoire pour ce qui touche au plan (2026-10-01)
- [DEC-005](./DECISIONS.md#dec-005) : registres de sources en CSV, orientation comme repère de lecture (2026-10-01)

## Apprentissages clés
- [LRN-001](./LEARNINGS.md#lrn-001) : depuis une session cloud, YouTube et les flux RSS sont inaccessibles ; tester en local (2026-10-01)
- [LRN-002](./LEARNINGS.md#lrn-002) : yt-dlp a besoin d'un moteur JavaScript (Deno) pour YouTube (2026-10-01)
- [LRN-003](./LEARNINGS.md#lrn-003) : `Element.iter()` ignore le joker `{*}` ; utiliser `iterfind(".//{*}item")` (2026-10-01)
- [LRN-004](./LEARNINGS.md#lrn-004) : un « ; » dans une note du registre CSV décale la ligne et désactive la source (2026-10-01)

## Blocages actifs
- [BLK-001](./BLOCKERS.md#blk-001) : lien de la vidéo Finary « Personne n'est prêt pour 2027 » à fournir (2026-10-01)

## Dernière itération
- [2026-10-01](./ITERATION_LOG.md) : mise en route locale : dépôt rattaché à `E:\formation`, 43 flux sur 48 validés, lecteur de flux rendu tolérant

## État courant
→ Voir [CONTEXT.md](./CONTEXT.md)
