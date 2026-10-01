---
name: croiser
description: Vérifie une affirmation ou éclaire une question en croisant au moins trois sources indépendantes (pays, orientation, type), la source primaire d'abord, et rend un verdict avec niveau de confiance. À utiliser pour « est-ce vrai que… », « vérifie », « qu'en disent les autres pays ? », ou un chiffre douteux. Produit veille/verifications/AAAA-MM-JJ-<sujet>.md.
argument-hint: "affirmation ou question"
allowed-tools: Read, Write, Edit, Glob, Grep, WebSearch, WebFetch, Agent
---

# /croiser — trois sources, une primaire, un verdict

Affirmation ou question : `$ARGUMENTS`

## 1. Reformuler
Écrire l'affirmation de façon vérifiable : quoi, qui, quand, combien. Une affirmation vague se découpe en
plusieurs ; chacune aura son verdict. Noter l'origine (vidéo, article, personne, rumeur).

## 2. Chercher (agent `chercheur`)
Déléguer à `chercheur` : « Vérifier : … Trouver d'abord la source primaire (texte officiel, données,
rapport, décision, déclaration enregistrée), puis au moins deux lectures de pays ou de lignes éditoriales
différents, et la meilleure source qui contredit. Dater tout. Signaler les sources circulaires. »
Pour une question de droit international, inclure les textes (traités, décisions de la CIJ, résolutions
de l'ONU) et un commentaire académique (EJIL: Talk!, Just Security, Opinio Juris).

## 3. Rendre le verdict
Créer `veille/verifications/AAAA-MM-JJ-<sujet>.md` à partir de `modeles/verification.md` :
- verdict : **confirmé** / **partiellement confirmé** / **non confirmé** / **faux** / **indéterminé** ;
- niveau de confiance et **ce qui changerait le verdict** ;
- écarts et nuances (où l'affirmation force le trait) ;
- sources avec niveau (A à E) et date.
« Indéterminé » est un verdict honnête quand les sources manquent ; « on ne peut pas savoir » n'est pas
un argument pour croire l'affirmation.

## 4. Propager
- Reporter le verdict dans la note d'origine (fiche vidéo, dossier, brief) par un lien.
- Si l'affirmation portait sur un signal du plan, mettre à jour `plan/signaux.md`.
- Répondre à l'utilisateur en quatre lignes : affirmation reformulée, verdict, meilleure source, nuance.

## Garde-fous
- Trois articles reprenant la même dépêche = une source.
- Un média d'État parlant de son gouvernement établit la position officielle, pas le fait.
- Ne jamais compléter une source manquante par une supposition.
