# Formation bourse : audio, transcription et planning

Outil personnel pour une formation **Podia** à laquelle vous êtes inscrit (ici « Investir en bourse » de Zonebourse). Il fait quatre choses :

1. **Inventaire** : liste toutes les leçons (vidéos, articles, quiz, fiches PDF), mesure la durée réelle des vidéos et le temps de lecture des articles.
2. **Audio** : récupère la piste son de chaque vidéo (fichiers `.m4a`).
3. **Transcription** : transcrit l'audio en texte français avec Whisper, sur votre ordinateur, avec les réglages les plus précis.
4. **Planning** : découpe la formation en séances d'**au moins 1 h** par jour et produit un fichier agenda (`.ics`).

L'outil ouvre une fenêtre de navigateur où **vous vous connectez vous-même** à Podia. Il ne voit ni ne stocke votre mot de passe. Il utilise uniquement votre accès d'élève inscrit : pas de contournement de DRM, et si une vidéo en avait, l'outil le signale et passe à la suivante.

> Usage strictement personnel : les contenus restent la propriété de Zonebourse. Ne partagez pas les fichiers audio ni les transcriptions.

---

## 1. Installation sous Windows (une seule fois, environ 15 minutes)

### 1.1 Installer Python 3.12

1. Téléchargez **Python 3.12** : <https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe>
   (n'installez pas la toute dernière version, 3.15, pas encore prise en charge par Whisper).
2. Lancez l'installateur et **cochez « Add python.exe to PATH »** en bas de la première fenêtre, puis « Install Now ».
3. À la fin, si le bouton **« Disable path length limit »** apparaît, cliquez dessus.

### 1.2 Télécharger l'outil dans `C:\formation`

1. Sur la page GitHub du projet, bouton vert **Code → Download ZIP**.
2. Ouvrez le ZIP : il contient un dossier au nom très long. **Copiez le contenu de ce dossier** (les dossiers `podia_formation`, `tests` et les fichiers `README.md`, `installer_windows.bat`…) dans un nouveau dossier **`C:\formation`**.
   Un chemin court évite les erreurs de chemin trop long de Windows. Évitez aussi les dossiers synchronisés par OneDrive (« Documents », « Bureau »).

### 1.3 Lancer l'installation

Double-cliquez sur **`C:\formation\installer_windows.bat`**. Il :
- crée l'environnement Python de l'outil ;
- installe les bibliothèques (yt-dlp, Playwright, faster-whisper…) ;
- détecte votre **carte graphique NVIDIA** et installe alors les bibliothèques CUDA (environ 1 Go).

Attendez le message **« Installation terminée »**. S'il y a une erreur, copiez le texte affiché.

L'outil utilise **Microsoft Edge**, déjà présent sur Windows : rien d'autre à installer.

### 1.4 Ouvrir l'invite de commandes au bon endroit

Toutes les commandes de ce guide se tapent dans l'**invite de commandes** ouverte dans `C:\formation` :
ouvrez le dossier `C:\formation` dans l'Explorateur, cliquez dans la barre d'adresse, tapez **`cmd`** puis Entrée.

<details>
<summary>macOS / Linux</summary>

Installez Python 3.12 (python.org, ou `brew install python@3.12`), puis dans le dossier de l'outil :

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium     # si Chrome n'est pas installé
```

Remplacez ensuite `formation` par `.venv/bin/python -m podia_formation` dans les commandes ci-dessous. Sous Linux avec une carte NVIDIA : `.venv/bin/python -m pip install -r requirements-gpu.txt`. Sur Mac, la transcription se fait sur le processeur.
</details>

---

## 2. Utilisation

Adresse de la formation (ou de n'importe quelle leçon) :

```
https://zonebourse.podia.com/p/courses/investir-en-bourse
```

### Étape 0 : se connecter (une seule fois)

L'outil utilise son propre profil de navigateur, séparé de votre Edge ou Chrome habituel : il faut donc vous y connecter une fois. Pendant la connexion, la fenêtre est un Edge tout à fait normal, que l'outil ne pilote pas : la vérification anti-robot de Cloudflare passe comme d'habitude. L'outil ne prend la main qu'après votre connexion.

```bat
formation connexion "https://zonebourse.podia.com/p/courses/investir-en-bourse/341465-module-2-se-lancer/973576-se-lancer"
```

- Une fenêtre Edge s'ouvre sur la page de connexion de Podia.
- **Connectez-vous** : e-mail, vérification Cloudflare (cochez la case si elle s'affiche), mot de passe, puis le code reçu par e-mail si demandé. Cochez « faire confiance à cet appareil ».
- **Revenez dans la fenêtre noire et appuyez sur Entrée.**
- Le message **`OK : vous êtes connecté`** confirme la connexion. Elle est gardée pour toutes les commandes suivantes.

Pour utiliser Chrome au lieu d'Edge, ajoutez `--navigateur chrome` à toutes les commandes.

### Étape 1 : la sonde (2 minutes)

Elle vérifie sur **une seule leçon** que tout fonctionne avec votre compte :

```bat
formation sonde "https://zonebourse.podia.com/p/courses/investir-en-bourse/341465-module-2-se-lancer/973576-se-lancer"
```

- L'outil analyse la leçon et récupère son audio dans `formation\sonde\audio\`.
- Si la connexion n'est plus valable, il rouvre la page de connexion et vous demande de vous connecter, puis d'appuyer sur Entrée.
- Tout va bien si vous voyez **`OK : Audio récupéré`**. Sinon, envoyez le texte affiché et la capture `formation\diagnostic\sonde.png`.

### Étape 2 : inventaire + audio de toute la formation

```bat
formation audio "https://zonebourse.podia.com/p/courses/investir-en-bourse"
```

Comptez 30 à 60 minutes pour environ 94 leçons. À la fin, l'outil affiche **le nombre d'heures de vidéo**, le temps de lecture des articles et le temps d'étude total estimé. Le détail est dans `formation\resume.md`.

Pour avoir seulement l'inventaire et les durées, sans télécharger l'audio : `formation inventaire "<adresse>"`. Les textes des articles et les fiches PDF sont récupérés dans les deux cas.

### Étape 3 : transcription en texte

```bat
formation transcrire
```

- **Premier lancement** : téléchargement du modèle Whisper `large-v3`, environ 3 Go, avec une barre de progression.
- **Carte graphique** : l'outil la teste et choisit tout seul le réglage. Sur une GeForce GTX 1650 (4 Go), c'est la précision `int8_float16`. Vérifiez que le message **« GPU retenu »** s'affiche.
- **Durée** : sur une GTX 1650, **environ 3 à 4 h pour 10 h d'audio** (estimation). Sur un processeur seul, **une nuit ou plus**. Vous pouvez interrompre (Ctrl+C) et relancer : les leçons déjà faites sont gardées.
- **Plus rapide** : `--modele large-v3-turbo`, 3 à 4 fois plus rapide, pour une qualité à peine inférieure.
- **Modèle spécialisé français** : `--modele francais` utilise [whisper-large-v3-french](https://huggingface.co/bofenghuang/whisper-large-v3-french), le large-v3 affiné sur du français et annoncé plus précis sur les longs enregistrements. Pour comparer sur une leçon avant de tout lancer :
  `formation transcrire --lecons 2 --modele francais --forcer`
  `--forcer` remplace la transcription existante de cette leçon ; relisez, puis gardez le modèle que vous préférez.

**Réglages de qualité utilisés** :
- modèle `large-v3`, le plus précis de Whisper ;
- langue forcée en français ;
- recherche en faisceau (beam 5) ;
- filtre des silences, pour éviter les phrases inventées ;
- un contexte en français et des mots-clés rappelés à Whisper **tout au long de chaque vidéo** : titre de la leçon et termes boursiers (PEA-PME, ETF, CAC 40, MSCI World, EBITDA…) ;
- un filtre des phrases que Whisper invente parfois (« Sous-titrage Société Radio-Canada », « Merci d'avoir regardé »…) et des répétitions en boucle.

Vous pouvez ajouter vos propres termes (noms propres, sigles), un par ligne, dans un fichier texte :

```bat
formation transcrire --vocabulaire mes_termes.txt
```

### Étape 4 : planning

```bat
formation planning --debut 01/10/2026 --heure 20h00 --minutes 60 --jours tous
```

- **Jours** : `--jours semaine` (du lundi au vendredi), `--jours lun-ven`, `--jours week-end` ou `--jours lun,mer,ven`.
- **Point de départ** : `--a-partir-de 12` démarre le planning à la leçon n°12.
- **Temps par vidéo** : `--facteur-video 1.5` compte plus de temps de pause et de notes par minute de vidéo (1.25 par défaut).
- **Réglages mémorisés** : ils sont conservés pour les relances suivantes.

Le planning est dans `formation\planning.md`. Pour l'agenda, importez `formation\planning.ics` dans Google Agenda (**Paramètres → Importer et exporter → Importer**), Outlook ou Apple Calendrier. Si vous réimportez un planning mis à jour, les séances sont modifiées plutôt que dupliquées.

### Tout d'un coup

```bat
formation tout "https://zonebourse.podia.com/p/courses/investir-en-bourse" --debut 01/10/2026
```

---

## 3. Ce que vous obtenez (dossier `C:\formation\formation\`)

| Fichier / dossier | Contenu |
|---|---|
| `resume.md` | Heures de vidéo, temps de lecture, temps d'étude total, détail par module |
| `inventaire.csv` | Tableau de toutes les leçons (s'ouvre dans Excel) |
| `audio\` | `M02-L01 - Se lancer.m4a`… (module, leçon, titre) |
| `transcriptions\` | Pour chaque vidéo : `.txt` (texte en paragraphes), `.md` (avec minutage), `.srt` (sous-titres) |
| `textes\` | Le texte des articles et des pages de leçon |
| `fichiers\` | Les fiches PDF jointes aux leçons |
| `sous-titres\` | Sous-titres fournis par la plateforme, s'il y en a |
| `formation_complete.md` | **Toute la formation en un seul document**, dans l'ordre : transcriptions et articles |
| `planning.md`, `planning.ics` | Le planning jour par jour et le fichier agenda |

Toutes les commandes peuvent être relancées : ce qui est déjà fait est conservé (`--forcer` pour tout refaire). N'ouvrez qu'une commande à la fois : une deuxième commande lancée sur le même dossier est refusée.

---

## 4. Comment le temps d'étude est estimé

- **Vidéo** : durée réelle × 1,25, pour les pauses et la prise de notes (modifiable avec `--facteur-video`).
- **Articles** : 200 mots par minute.
- **Quiz** : 1 minute par question (3 minutes au minimum), ou 5 minutes si le nombre de questions n'est pas visible.
- **Fiches PDF** : 2 minutes par page.
- **Vidéo dont la durée n'a pas pu être mesurée** : durée typique des autres vidéos, signalée « (durée estimée) » dans le planning.

Le planning fait **autant de séances que possible en gardant chacune à au moins 1 h**. Il répartit les leçons dans l'ordre, sans les couper, de façon aussi régulière que possible.

---

## 5. Dépannage

| Symptôme | Solution |
|---|---|
| « Échec de la vérification » (Cloudflare) sur la page de connexion | Fermez toutes les fenêtres ouvertes par l'outil, mettez l'outil à jour, puis relancez `formation connexion`. Si la vérification échoue encore, cliquez sur « Résolution de problèmes » ou rechargez la page (F5) dans la même fenêtre. |
| « Vous n'êtes pas connecté à Podia » | Lancez `formation connexion "<adresse>"`, connectez-vous dans la fenêtre, puis appuyez sur Entrée. Le travail déjà fait est gardé. |
| « Aucune leçon trouvée » ou « lecteur vidéo repéré mais flux non capté » | Relancez avec `--diagnostic`. Le dossier `formation\diagnostic\` contient la page, les requêtes réseau et une capture d'écran. E-mail, nom et liens signés y sont masqués, mais la capture montre la page telle quelle : vérifiez-la avant de l'envoyer. |
| « leçon inaccessible (verrouillée ?) » | La leçon n'est pas encore ouverte (déblocage progressif) : elle sera reprise à un prochain lancement. |
| « Impossible de lancer un navigateur » | `formation audio … --navigateur chrome`, ou `.venv\Scripts\python -m playwright install chromium`. |
| « Impossible de charger Whisper » | Installez le composant Microsoft **Visual C++ Redistributable x64** : <https://aka.ms/vs/17/release/vc_redist.x64.exe>, puis relancez. |
| « Le GPU est inutilisable » | Relancez `installer_windows.bat` (il installe les bibliothèques CUDA) et mettez à jour le pilote NVIDIA. Pour forcer un réglage : `--precision int8`. |
| « vidéo protégée par DRM » | La vidéo ne peut pas être récupérée ; l'outil passe à la suivante. |
| « fermez-le s'il est ouvert (Excel…) » | Fermez `inventaire.csv` dans Excel, puis relancez. |
| Les téléchargements échouent tous d'un coup | Mettez yt-dlp à jour : `.venv\Scripts\python -m pip install -U yt-dlp`. |

Le profil du navigateur, qui garde votre connexion, est dans `C:\Users\<vous>\.podia_formation\navigateur`. Supprimez ce dossier pour vous déconnecter complètement.

---

## 6. Fonctionnement technique (pour les curieux)

- Podia héberge ses vidéos chez **Cloudflare Stream** depuis 2024. Le lecteur est une iframe dont l'adresse contient un **jeton signé temporaire**. L'outil en déduit l'adresse du flux HLS, ou la capte au moment où le lecteur la demande. Il télécharge alors **la piste audio seule** avec [yt-dlp](https://github.com/yt-dlp/yt-dlp), juste après la visite de la leçon, avant que le jeton n'expire. Un segment manquant fait échouer le téléchargement, qui est retenté, plutôt que de laisser un trou dans la transcription.
- Les vidéos Vimeo, Loom et l'ancien Wistia sont aussi prises en charge. Les vidéos YouTube demandent en plus [Deno](https://deno.com) (`winget install DenoLand.Deno`).
- La transcription utilise [faster-whisper](https://github.com/SYSTRAN/faster-whisper), une implémentation rapide de Whisper. L'audio est converti avec PyAV : aucun ffmpeg à installer.
- Tests : `pip install -r requirements-dev.txt` puis `pytest`. Ils s'exécutent sur un faux site Podia local, avec un vrai navigateur et un vrai yt-dlp. Indiquez le chemin d'un Chromium dans la variable `PODIA_TEST_CHROMIUM` pour les tests de bout en bout.
