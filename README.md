# clippey

Génère des clips verticaux courts à partir d'une vidéo longue. À partir d'une URL YouTube :
téléchargement, transcription, sélection des meilleurs passages par LLM, recadrage 9:16
suivant les visages, sous-titres karaoké incrustés, puis titre, description et hashtags
pour chaque clip.

Tout le traitement est local. Seul l'appel LLM passe par le réseau, plafonné à 0,50 € par
vidéo.

<details>
<summary><b>In English</b></summary>

clippey turns a long video into short vertical clips. Give it a YouTube URL: it downloads
the video, transcribes it locally, asks an LLM to pick the best self-contained moments,
reframes them to 9:16 with face tracking, burns in karaoke subtitles, and writes a title,
description and hashtags for each clip.

All processing is local. Only the LLM call hits the network, capped at €0.50 per video.

Requires macOS on Apple Silicon, Homebrew `ffmpeg-full`, [uv](https://docs.astral.sh/uv/),
and an OpenAI-compatible LLM API key.

```bash
brew install ffmpeg-full
git clone https://github.com/LsTam91/clippey.git && cd clippey && uv sync
export CLIPPEY_LLM__API_KEY=sk-...
uv run clippey run "https://www.youtube.com/watch?v=VIDEO_ID"
open data/VIDEO_ID/review.html
```

The README, CLI and code are in French.

</details>

## Pipeline

```
URL YouTube
    ├─ ingest    téléchargement et normalisation (source.mp4 → norm.mp4, audio, proxy)
    ├─ asr       transcription locale, timestamps au mot (Whisper)
    ├─ audio     pics d'énergie (rires, cris, applaudissements)
    ├─ visual    découpage en scènes, détection des visages
    ├─ select    sélection des meilleurs passages par LLM
    ├─ compose   recadrage 9:16, sous-titres karaoké, encodage
    ├─ caption   titre, description, hashtags
    └─ package   manifest.json et galerie HTML de relecture
    │
    └─→ data/<video_id>/clips/*.mp4
```

Les étapes sont reprenables : relancer la commande saute celles déjà terminées dont la
configuration n'a pas changé. Modifier un réglage n'invalide que l'étape concernée et les
suivantes.

## Sortie

Des `.mp4` verticaux 1080×1920 :

- recadrage suivant le visage dominant, recalculé à chaque changement de plan ;
- sous-titres karaoké mot par mot, police Anton fournie ;
- accroche affichée pendant les 2,5 premières secondes ;
- assemblage possible de 3 passages non contigus de la source en un seul clip ;
- silence d'une seconde après le dernier mot, plutôt qu'une coupe sèche ;
- audio normalisé à −14 LUFS ;
- titre, description et hashtags par clip.

Une galerie `review.html` regroupe les clips et leurs légendes.

## Prérequis

| | |
|---|---|
| macOS sur Apple Silicon | La transcription passe par [mlx-whisper](https://github.com/ml-explore/mlx-examples), limité aux puces Apple. Voir [Autres plateformes](#autres-plateformes). |
| `ffmpeg-full` (Homebrew) | Le paquet `ffmpeg` standard n'inclut plus libass, requis pour incruster les sous-titres. |
| [uv](https://docs.astral.sh/uv/) | Gestionnaire de paquets Python. |
| Une clé API LLM | Endpoint compatible OpenAI. Par défaut [DeepSeek](https://platform.deepseek.com/). |

Prévoir environ 6 Go d'espace disque : modèle Whisper et fichiers intermédiaires.

## Installation

```bash
brew install ffmpeg-full
curl -LsSf https://astral.sh/uv/install.sh | sh   # si uv n'est pas installé

git clone https://github.com/LsTam91/clippey.git
cd clippey
uv sync
```

Le premier lancement télécharge le modèle de transcription (~1,5 Go, une seule fois).

Renseigner ensuite la clé API :

```bash
export CLIPPEY_LLM__API_KEY=sk-xxxxxxxxxxxxxxxx
```

Elle peut aussi vivre dans `clippey.local.toml`, ignoré par git — voir
[Configuration](#configuration).

## Utilisation

```bash
uv run clippey run "https://www.youtube.com/watch?v=VIDEO_ID"
open data/VIDEO_ID/review.html
```

Compter 5 à 15 minutes pour une vidéo d'une heure. La commande affiche sa progression et se
termine sur le coût API réel. Les fichiers sont dans `data/VIDEO_ID/clips/`.

Pour une liste d'URLs, une par ligne, les lignes commençant par `#` étant ignorées :

```bash
uv run clippey batch mes-videos.txt
```

Un échec sur une vidéo n'interrompt pas le lot.

### Commandes

| Commande | Rôle |
|---|---|
| `clippey run <url>` | Pipeline complet. |
| `clippey run <url> --until select` | S'arrête après l'étape indiquée. |
| `clippey batch <fichier.txt>` | Liste d'URLs. |
| `clippey status <video_id>` | État des étapes et coût API. |
| `clippey rate <clip_id> --stars 4` | Note un clip. |
| `ingest` `asr` `visual` `select` `compose` `caption` `package` | Rejoue une étape seule. |

Toutes acceptent `--charte`.

## Configuration

Deux fichiers distincts.

`clippey.toml` (ou `clippey.local.toml`, ignoré par git) porte la configuration technique :
clé API, modèle, chemins des binaires. Toutes les options sont surchargeables par variables
d'environnement `CLIPPEY_*`.

```bash
cp clippey.toml.example clippey.local.toml
```

Les chartes (`chartes/*.toml`) portent le style des clips : durée, nombre, apparence des
sous-titres, hashtags de base, ton éditorial.

```bash
cp chartes/default.toml chartes/moncreateur.toml
uv run clippey run "https://youtu.be/..." --charte chartes/moncreateur.toml
```

Référence complète des deux fichiers : [docs/configuration.md](docs/configuration.md).

## Coût

Deux appels LLM par vidéo, plus une passe de relecture. Mesuré avec `deepseek-chat` :
0,002 à 0,004 € pour une vidéo de 15 minutes. `max_cost_per_video_eur` (0,50 € par défaut)
interrompt tout appel au-delà du plafond.

Les réponses LLM sont mises en cache sur disque : rejouer une étape aux mêmes entrées ne
coûte rien.

```bash
uv run clippey status VIDEO_ID
```

Téléchargement, transcription et encodage sont locaux et gratuits.

## Arborescence

```
data/<video_id>/
  source.mp4 norm.mp4 audio.wav proxy480.mp4   # média (norm.mp4 = référence temporelle)
  meta.json transcript.json selection.json      # artefacts intermédiaires
  captions.json                                 # titres, descriptions, hashtags
  llm_cache/                                    # réponses LLM
  clips/<clip_id>.mp4 + .ass                    # clips finis et sous-titres
  manifest.json review.html                     # récapitulatif et galerie
data/clippey.db                                 # étapes, coûts, notes
```

`data/` est ignoré par git.

## Dépannage

**Pas de sous-titres à l'image, ou `Unable to find a suitable output format`**
ffmpeg sans libass. Vérifier `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg` ; si le binaire est
ailleurs, renseigner `ffmpeg_path`.

**`Sign in to confirm you're not a bot`**
YouTube exige une session. Renseigner `cookies_from_browser = "firefox"` (ou `chrome`,
`safari`).

**`ModuleNotFoundError: mlx_whisper`**
mlx-whisper ne s'installe que sur macOS Apple Silicon. Voir ci-dessous.

**Aucun clip produit, ou erreur LLM**
Vérifier que `CLIPPEY_LLM__API_KEY` est exportée dans le shell courant. Si l'étape `caption`
échoue, le pipeline se termine avec les titres produits par `select`.

**Une étape est sautée alors qu'elle doit être rejouée**
Comportement normal de la reprise. L'appeler directement : `uv run clippey select VIDEO_ID`.

### Autres plateformes

Seule la transcription dépend de la plateforme. Sur Linux ou Windows, remplacer `step_asr`
dans [`src/clippey/analyze/asr.py`](src/clippey/analyze/asr.py) par un backend équivalent —
`faster-whisper` est déjà déclaré en dépendance optionnelle (`uv sync --extra gpu`). Le
contrat est de produire un `Transcript` avec des timestamps au mot.

## Développement

```bash
uv run pytest
uv run ruff check src tests && uv run ruff format src tests
```

43 tests, sans appel réseau ni encodage. Architecture et conventions :
[docs/architecture.md](docs/architecture.md).

## Droits

Clipper une vidéo n'en transfère pas les droits. Vérifier l'autorisation de la source, ou
l'applicabilité d'une exception dans la juridiction concernée, avant toute diffusion. Les
vidéos filmant des personnes identifiables sans leur consentement sont le premier motif de
retrait sur ce type de contenu.

## Licence

MIT — voir [LICENSE](LICENSE).

Ressources embarquées :
- police **Anton**, © The Anton Project Authors, [SIL Open Font License 1.1](fonts/OFL-Anton.txt) ;
- modèle **BlazeFace** (`models/blaze_face_short_range.tflite`), issu de
  [MediaPipe](https://developers.google.com/mediapipe), Apache 2.0.

Construit avec [yt-dlp](https://github.com/yt-dlp/yt-dlp), [ffmpeg](https://ffmpeg.org/),
[MLX](https://github.com/ml-explore/mlx), [MediaPipe](https://developers.google.com/mediapipe)
et [PySceneDetect](https://www.scenedetect.com/).
