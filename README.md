# Formation bourse : audio, transcription et planning

Outil personnel pour une formation **Podia** à laquelle vous êtes inscrit (ici « Investir en bourse » de Zonebourse). Il fait quatre choses :

1. **Inventaire** : liste toutes les leçons (vidéos, articles, quiz, fiches PDF), mesure la durée réelle des vidéos et le temps de lecture des articles.
2. **Audio** : récupère la piste son de chaque vidéo (fichiers `.m4a`).
3. **Transcription** : transcrit l'audio en texte français avec Whisper, sur votre ordinateur, avec les réglages les plus précis.
4. **Planning** : découpe la formation en séances d'au moins 1 h par jour et produit un fichier agenda (`.ics`).

L'outil ouvre une fenêtre de navigateur où **vous vous connectez vous-même** à Podia. Il ne voit ni ne stocke votre mot de passe. Il utilise uniquement votre accès d'élève inscrit : pas de contournement de DRM, et si une vidéo en avait, l'outil le signale et passe à la suivante.

> Usage strictement personnel : les contenus restent la propriété de Zonebourse. Ne partagez pas les fichiers audio ni les transcriptions.

---

## 1. Installation (une seule fois)

### Windows

1. Installez **Python 3.10 ou plus récent** depuis <https://www.python.org/downloads/>. Pendant l'installation, **cochez « Add python.exe to PATH »**.
2. Téléchargez ce projet : bouton vert **Code → Download ZIP** sur GitHub, puis décompressez-le (par exemple dans `Documents\formation_bourse_transcripte`).
3. Ouvrez le dossier dans l'Explorateur, tapez `cmd` dans la barre d'adresse puis Entrée. Dans la fenêtre noire, copiez :

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Carte graphique NVIDIA (fortement recommandé pour la transcription)

Si votre PC a une carte NVIDIA (par exemple une GeForce GTX 1650), installez en plus les bibliothèques CUDA (environ 1 Go) :

```bat
pip install -r requirements-gpu.txt
```

L'outil teste la carte au démarrage de la transcription et choisit tout seul le bon réglage. Sur une carte de 4 Go comme la GTX 1650, il prend la précision `int8_float16` : environ 3 Go de mémoire, pour une perte de précision négligeable. Si la carte ne fonctionne pas, il bascule automatiquement sur le processeur. Pensez à garder le pilote NVIDIA à jour (GeForce Experience ou nvidia.com).

### Navigateur

L'outil utilise **Microsoft Edge** (présent sur tous les Windows) ou **Google Chrome** s'ils sont installés. Sinon, installez le navigateur de Playwright :

```bash
python -m playwright install chromium
```

> À chaque nouvelle session, réactivez l'environnement : `.venv\Scripts\activate` (Windows) ou `source .venv/bin/activate` (macOS/Linux).

---

## 2. Utilisation

Adresse de la formation (ou de n'importe quelle leçon) :

```
https://zonebourse.podia.com/p/courses/investir-en-bourse
```

### Étape 1 : la sonde (2 minutes, à faire en premier)

Elle vérifie sur **une seule leçon** que tout fonctionne avec votre compte :

```bash
python -m podia_formation sonde "https://zonebourse.podia.com/p/courses/investir-en-bourse/341465-module-2-se-lancer/973576-se-lancer"
```

- Une fenêtre de navigateur s'ouvre : **connectez-vous à Podia** (e-mail, mot de passe, et code reçu par e-mail si demandé ; cochez « faire confiance à cet appareil »).
- L'outil reprend tout seul, analyse la leçon et récupère son audio dans `formation/sonde/audio/`.
- Tout va bien si vous voyez `✅ Audio récupéré`. Sinon, voyez la section **Dépannage**.

### Étape 2 : inventaire + audio de toute la formation

```bash
python -m podia_formation audio "https://zonebourse.podia.com/p/courses/investir-en-bourse"
```

Comptez 30 à 60 minutes pour environ 94 leçons. À la fin, l'outil affiche **le nombre d'heures de vidéo**, le temps de lecture des articles et le temps d'étude total estimé. Le détail est dans `formation/resume.md`.

Pour avoir seulement les durées, sans rien télécharger : `python -m podia_formation inventaire "<adresse>"`.

### Étape 3 : transcription en texte

```bash
python -m podia_formation transcrire
```

- **Premier lancement** : téléchargement du modèle Whisper `large-v3`, environ 3 Go.
- **Durée** : sur une GTX 1650, comptez **environ 3 à 4 h pour 10 h d'audio** (estimation). Une carte plus récente va plus vite ; sur un processeur seul, **comptez une nuit ou plus**. Le travail peut être interrompu (Ctrl+C) et repris : les leçons déjà faites sont gardées.
- Pour aller 3 à 4 fois plus vite, avec une qualité à peine inférieure : `--modele large-v3-turbo`.
- **Modèle spécialisé français** : `--modele francais` utilise [whisper-large-v3-french](https://huggingface.co/bofenghuang/whisper-large-v3-french), le large-v3 affiné sur du français, annoncé plus précis sur les longs enregistrements. Pour comparer sur une leçon avant de tout lancer, transcrivez-la avec chaque modèle et relisez : `python -m podia_formation transcrire --lecons 2 --modele francais --forcer` (`--forcer` remplace la transcription existante de cette leçon).

**Réglages de qualité utilisés** :
- modèle `large-v3` (le plus précis de Whisper) ;
- langue forcée en français ;
- recherche en faisceau (beam 5) ;
- filtre des silences, pour éviter les phrases inventées ;
- un contexte en français et des mots-clés rappelés à Whisper **tout au long de chaque vidéo** (titre de la leçon, termes boursiers : PEA-PME, ETF, CAC 40, MSCI World, EBITDA…) pour bien écrire les termes techniques ;
- un filtre des phrases que Whisper invente parfois (« Sous-titrage Société Radio-Canada », « Merci d'avoir regardé »…) et des répétitions en boucle.

Vous pouvez ajouter vos propres termes (noms propres, sigles), un par ligne, dans un fichier :

```bash
python -m podia_formation transcrire --vocabulaire mes_termes.txt
```

### Étape 4 : planning

```bash
python -m podia_formation planning --debut 2026-10-01 --heure 20:00 --minutes 60 --jours tous
```

- `--jours semaine` (du lundi au vendredi) ou `--jours lun,mer,ven,dim`.
- `--a-partir-de 12` démarre le planning à la leçon n°12.
- `--facteur-video 1.5` compte plus de temps de pause et de notes par minute de vidéo (1.25 par défaut).

Le planning est dans `formation/planning.md`. Importez `formation/planning.ics` dans Google Agenda (**Paramètres → Importer et exporter → Importer**), Outlook ou Apple Calendrier.

### Tout d'un coup

```bash
python -m podia_formation tout "https://zonebourse.podia.com/p/courses/investir-en-bourse" --debut 2026-10-01
```

---

## 3. Ce que vous obtenez (dossier `formation/`)

| Fichier / dossier | Contenu |
|---|---|
| `resume.md` | Heures de vidéo, temps de lecture, temps d'étude total, détail par module |
| `inventaire.csv` | Tableau de toutes les leçons (s'ouvre dans Excel) |
| `audio/` | `M02-L01 - Se lancer.m4a`… (module, leçon, titre) |
| `transcriptions/` | Pour chaque vidéo : `.txt` (texte en paragraphes), `.md` (avec minutage), `.srt` (sous-titres) |
| `textes/` | Le texte des articles et des pages de leçon |
| `fichiers/` | Les fiches PDF jointes aux leçons |
| `sous-titres/` | Sous-titres fournis par la plateforme, s'il y en a |
| `formation_complete.md` | **Toute la formation en un seul document**, dans l'ordre : transcriptions et articles |
| `planning.md`, `planning.ics` | Le planning jour par jour et le fichier agenda |

Toutes les commandes peuvent être relancées : ce qui est déjà fait est conservé (`--forcer` pour tout refaire).

---

## 4. Comment le temps d'étude est estimé

- **Vidéo** : durée réelle × 1,25, pour les pauses et la prise de notes (modifiable avec `--facteur-video`).
- **Articles** : 200 mots par minute.
- **Quiz** : 1 minute par question (3 minutes au minimum), ou 5 minutes si le nombre de questions n'est pas visible.
- **Fiches PDF** : 2 minutes par page.

Le planning prend le nombre de séances qui donne **au moins 1 h en moyenne par séance**, puis répartit les leçons dans l'ordre, sans les couper, de façon aussi régulière que possible.

---

## 5. Dépannage

| Symptôme | Solution |
|---|---|
| « Session absente ou expirée » | Relancez **sans** `--headless` pour vous reconnecter dans la fenêtre. |
| « Aucune leçon trouvée » ou « lecteur vidéo repéré mais flux non capté » | Relancez avec `--diagnostic`. Le dossier `formation/diagnostic/` contient la page, les requêtes réseau (liens signés masqués) et une capture d'écran. |
| « Impossible de lancer un navigateur » | `python -m playwright install chromium`, ou `--navigateur chrome` / `--navigateur msedge`. |
| « vidéo protégée par DRM » | La vidéo ne peut pas être récupérée ; l'outil passe à la suivante. |
| Transcription trop lente | Vérifiez que le message « GPU retenu » s'affiche. Sinon, installez `requirements-gpu.txt` et mettez à jour le pilote NVIDIA. En dernier recours : `--modele large-v3-turbo`. |
| « Le GPU est inutilisable » | Installez `pip install -r requirements-gpu.txt`, mettez à jour le pilote NVIDIA, puis relancez. Pour forcer un réglage : `--precision int8`. |

Le profil du navigateur, qui garde votre connexion, est dans `~/.podia_formation/navigateur` (`C:\Users\<vous>\.podia_formation\navigateur` sous Windows). Supprimez ce dossier pour vous déconnecter complètement.

---

## 6. Fonctionnement technique (pour les curieux)

- Podia héberge ses vidéos chez **Cloudflare Stream** depuis 2024. Le lecteur est une iframe dont l'adresse contient un **jeton signé temporaire**. L'outil en déduit l'adresse du flux HLS, ou la capte au moment où le lecteur la demande, puis télécharge **la piste audio seule** avec [yt-dlp](https://github.com/yt-dlp/yt-dlp), juste après la visite de la leçon, avant que le jeton n'expire.
- Les vidéos externes (YouTube, Vimeo, Loom, ancien Wistia) sont aussi prises en charge.
- La transcription utilise [faster-whisper](https://github.com/SYSTRAN/faster-whisper), une implémentation rapide de Whisper. L'audio est converti avec PyAV : aucun ffmpeg à installer.
- Tests : `pip install -r requirements-dev.txt` puis `pytest`. Ils s'exécutent sur un faux site Podia local, avec un vrai navigateur et un vrai yt-dlp.
