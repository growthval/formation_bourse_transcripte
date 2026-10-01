---
name: log
description: Capture une entrée de mémoire projet (décision, apprentissage, blocage ou itération) dans .claude/memory/ et met à jour l'index MEMORY.md. À utiliser après une décision d'architecture ou un changement notable.
argument-hint: '[decision|learning|blocker|iteration] "résumé"'
allowed-tools: Read, Edit, Write
---

# /log — capture mémoire

Enregistre une entrée dans le registre `.claude/memory/` et met à jour l'index, en suivant le format du fichier cible.

Argument reçu : `$ARGUMENTS` (1er mot = type, le reste = contenu).

## Procédure
1. **Type → fichier cible** :
   - `decision`  → `.claude/memory/DECISIONS.md` (préfixe `DEC-`)
   - `learning`  → `.claude/memory/LEARNINGS.md` (préfixe `LRN-`)
   - `blocker`   → `.claude/memory/BLOCKERS.md` (préfixe `BLK-`)
   - `iteration` → `.claude/memory/ITERATION_LOG.md` (entrée datée, la plus récente en haut)
   Type absent/ambigu → le demander.
2. Lire le fichier cible pour trouver le **prochain ID** (max existant + 1, format `XXX` sur 3 chiffres).
3. Ajouter une entrée au **format EXACT** du fichier (calquer ses entrées existantes). Date = aujourd'hui.
   - Compléter les champs depuis le contenu fourni + le contexte de la conversation.
   - Champ clé manquant → le demander brièvement, ne pas inventer.
4. Mettre à jour l'index `.claude/memory/MEMORY.md` : ligne 1-ligne (lien `#id` + date) + « Dernière itération » si besoin.
5. Confirmer avec ✅ : ID créé + fichiers touchés.

## Garde-fous
- Entrée **concise et curée** (le *pourquoi*), pas un dump. L'index = 1 ligne par entrée.
- Un blocage résolu passe au statut « résolu » et quitte la liste « Blocages actifs » de l'index.
