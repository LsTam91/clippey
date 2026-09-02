# Architecture

## Principe

Huit étapes séquentielles. Chacune lit des fichiers, écrit des fichiers, et ne communique
avec aucune autre directement. `pipeline.py` les enchaîne et gère la reprise.

```
ingest → asr → audio → visual → select → compose → caption → package
```

Toute la coordination passe par deux endroits :

- `data/<video_id>/` — les artefacts. Aucun état ne transite en mémoire entre deux étapes.
- `data/clippey.db` (SQLite) — avancement, coûts LLM, notes. Pas de contenu.

Chaque étape est donc rejouable seule (`clippey compose <video_id>`) et le pipeline
interruptible à tout moment.

## Timebase

Toutes les valeurs temporelles du projet sont des secondes flottantes depuis le début de
`norm.mp4`, pas de la source téléchargée. `ingest` normalise d'abord la vidéo — remux si
elle est déjà à débit d'images constant et démarre à zéro, ré-encodage sinon. Toute nouvelle
étape doit s'y conformer.

## Reprise et invalidation

`run_steps` calcule pour chaque étape une empreinte (`params_hash`) des réglages dont elle
dépend, déclarés dans `cli._steps()`.

- Étape `complete` avec la même empreinte : sautée.
- Empreinte différente : rejouée, et toutes les suivantes deviennent périmées même si leur
  propre empreinte n'a pas changé. Une sélection différente rend le rendu précédent caduc.

Le cache LLM (`data/<video_id>/llm_cache/`) est une seconde couche : un appel identique
(même modèle, mêmes messages) est resservi depuis le disque même lorsque l'étape est rejouée.

## Étapes

| Étape | Module | Entrées → sorties |
|---|---|---|
| `ingest` | `ingest.py` | URL → `source.mp4`, `norm.mp4`, `audio.wav`, `proxy480.mp4`, `meta.json` |
| `asr` | `analyze/asr.py` | `audio.wav` → `transcript.json` |
| `audio` | `analyze/audio_events.py` | `audio.wav` → `energy.json` |
| `visual` | `analyze/visual.py` | `proxy480.mp4` → `scenes.json`, `faces.json` |
| `select` | `select/brain.py` | `transcript.json` + `energy.json` → `selection.json` |
| `compose` | `compose/render.py` | `norm.mp4` + `selection.json` → `clips/<id>.mp4`, `.ass` |
| `caption` | `caption.py` | `selection.json` + `transcript.json` → `captions.json` |
| `package` | `package.py` | → `manifest.json`, `review.html` |

### ingest

yt-dlp récupère les métadonnées puis la vidéo. La heatmap « most replayed » de YouTube est
stockée dans `meta.json` mais n'est pas transmise au LLM : l'utiliser en entrée rendrait
circulaire toute évaluation fondée dessus.

Trois dérivés sont extraits de `norm.mp4` : l'audio 16 kHz mono pour la transcription, et un
proxy 480p pour l'analyse visuelle — la détection de visages sur du 1080p coûterait dix fois
plus cher à précision de cadrage égale.

### asr

`mlx-whisper` avec timestamps au mot. Deux post-traitements conditionnent le karaoké : la
ponctuation, renvoyée par Whisper en tokens séparés, est refusionnée dans le mot précédent,
et les élisions françaises (« C » + « 'est ») sont recollées. Les phrases sont découpées sur
la ponctuation forte ou sur une pause supérieure à `sentence_pause_s`.

Seule étape dépendante de la plateforme. La porter revient à réécrire `step_asr` pour
produire le même `Transcript`.

### select

Le LLM reçoit la transcription indexée par identifiants de phrases (`[S0042 @ 12:34] texte`)
et les pics d'énergie audio, et répond avec des identifiants de phrases, jamais des temps.
C'est le choix structurant du projet : un LLM produit des timestamps plausibles mais faux,
alors qu'un identifiant est soit valide, soit rejeté à la validation.

`refine_boundaries` calcule ensuite les bornes réelles : marges avant et après, accroche
placée dans les 3,5 premières secondes, souffle de fin, durée min/max. Suivent le classement
par score pondéré, le rejet sous `score_floor` et l'élimination des chevauchements.

Un clip peut assembler jusqu'à trois passages non contigus de la source.

Une passe de relecture (`critic_system`) vérifie que l'accroche et le titre ne divulguent pas
la chute, et les réécrit le cas échéant.

### compose

Un seul encodage ffmpeg par clip, quel que soit le nombre de passages. Le graphe de filtres
est construit dans `render.py` :

1. une entrée par morceau du plan de crop, avec seek précis ;
2. crop 9:16 morceau par morceau, centre horizontal issu du visage dominant médian
   (`reframe.py`), recalculé à chaque changement de plan, hystérésis de 6 % de la largeur ;
3. concaténation, puis souffle de fin (dernière image gelée, fondu audio) ;
4. incrustation du fichier ASS sur la timeline assemblée ;
5. `loudnorm` en deux passes vers −14 LUFS.

Le fichier ASS est généré à la main (`subtitles.py`) : le karaoké mot-à-mot n'est qu'une
suite de balises `\k` en centisecondes, ce qui évite une dépendance pour une centaine de
lignes.

### caption

Passe LLM séparée de `select` pour qu'un ajustement de copie ne relance pas un rendu de
plusieurs minutes. Elle ne lève jamais d'exception : si l'appel échoue, les titres produits
par `select` sont conservés et le pipeline continue.

Le budget `caption_max_chars` est appliqué deux fois, dans le prompt et par
`enforce_caption_budget`. Un prompt ne garantit pas une contrainte dure. Au-delà du budget,
la description est retirée en premier, puis les hashtags depuis la fin, puis le titre est
tronqué.

### package

`manifest.json` (contrat machine) et `review.html`, galerie autonome sans dépendance externe,
lisible depuis `file://`.

## Conventions

- **Pydantic aux frontières.** Tous les artefacts sont des modèles de `models.py`, relus par
  `model_validate_json`. Un fichier corrompu échoue au chargement, pas trois étapes plus loin.
- **Écritures atomiques.** `write_json_atomic` écrit un `.tmp` puis renomme. Une interruption
  ne laisse pas d'artefact partiel que la reprise prendrait pour valide.
- **Un seul point de sortie réseau vers le LLM** : `select/llm.py`. Cache, réparation JSON
  (3 tentatives), comptage des tokens et plafond de budget y sont centralisés. Le budget est
  vérifié avant l'appel.
- **Prompts versionnés** (`PROMPT_VERSION`, `CAPTION_PROMPT_VERSION` dans `select/prompts.py`),
  intégrés au `params_hash`. Modifier un prompt sans incrémenter sa version fait resservir
  d'anciens résultats.
- **Français dans le code comme dans la doc** : docstrings, commentaires, messages CLI.

## Tests

43 tests, sans appel réseau ni encodage vidéo : découpage de phrases, plan de crop,
génération ASS, ajustement des légendes, graphe ffmpeg construit mais non exécuté.

```bash
uv run pytest
uv run ruff check src tests && uv run ruff format src tests
```

## Ajouter une étape

1. Écrire `step_xxx(ctx: Context) -> None`, lisant et écrivant via `ctx.paths`.
2. Déclarer ses chemins d'artefacts dans `models.artifact_paths`.
3. L'ajouter à `cli._steps()` avec la fonction `params` listant les réglages dont elle dépend.
   Cette liste pilote l'invalidation : une omission produit des résultats périmés silencieux.
4. Exposer une commande `@app.command()` pour pouvoir la rejouer seule.
