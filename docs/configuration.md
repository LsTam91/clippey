# Configuration

clippey lit deux fichiers.

| Fichier | Contenu | Versionné |
|---|---|---|
| `clippey.toml` / `clippey.local.toml` | Clé API, modèle, binaires, dossiers | `.local.toml` est ignoré par git |
| `chartes/*.toml` | Durée, style, ton, hashtags | oui |

Aucun n'est obligatoire : sans fichier, clippey utilise ses valeurs par défaut. Seule la clé
API doit être fournie.

---

## Configuration technique

Résolution : `clippey.local.toml`, sinon `clippey.toml`, sinon les valeurs par défaut. Chaque
option est surchargeable par variable d'environnement préfixée `CLIPPEY_`, avec `__` pour
descendre d'un niveau (`[llm] api_key` → `CLIPPEY_LLM__API_KEY`).

```bash
cp clippey.toml.example clippey.local.toml
```

### Racine

| Option | Défaut | Rôle |
|---|---|---|
| `data_dir` | `"data"` | Emplacement des artefacts et de la base SQLite. |
| `ffmpeg_path` | `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg` | Doit pointer vers un ffmpeg compilé avec libass. Le `ffmpeg` standard de Homebrew ne l'a plus. |
| `ffprobe_path` | `/opt/homebrew/opt/ffmpeg-full/bin/ffprobe` | Inspection des fichiers. |
| `fonts_dir` | `"fonts"` | Dossier des polices passé à ffmpeg. La police est chargée depuis là, pas depuis le système. |
| `language` | `"fr"` | Langue par défaut si la vidéo ne la déclare pas. |
| `cookies_from_browser` | `""` | `firefox`, `chrome`, `safari`… Passe les cookies du navigateur à yt-dlp quand YouTube exige une session. |

### `[llm]`

| Option | Défaut | Rôle |
|---|---|---|
| `base_url` | `https://api.deepseek.com/v1` | Endpoint compatible OpenAI : OpenAI, OpenRouter, Groq, Ollama en local. |
| `api_key` | `""` | Clé API, ici ou dans `CLIPPEY_LLM__API_KEY`. |
| `model` | `"deepseek-chat"` | Modèle utilisé pour la sélection et les légendes. |
| `price_in_eur_per_mtok` | `0.13` | Prix d'entrée en €/million de tokens. À réajuster en cas de changement de modèle, sinon le compteur de coût est faux. |
| `price_out_eur_per_mtok` | `0.26` | Prix de sortie. |
| `max_cost_per_video_eur` | `0.50` | Plafond dur : au-delà, l'appel est refusé. |
| `timeout_s` | `120.0` | Délai maximal d'un appel. |

### `[asr]`

| Option | Défaut | Rôle |
|---|---|---|
| `model_repo` | `mlx-community/whisper-large-v3-turbo` | Modèle Whisper, téléchargé au premier lancement (~1,5 Go). Un modèle plus petit transcrit plus vite et moins bien ; la qualité des sous-titres en dépend directement. |
| `no_speech_threshold` | `0.6` | Au-dessus, le segment est traité comme du silence. |
| `logprob_threshold` | `-1.0` | Combiné au précédent, filtre les hallucinations de Whisper sur les passages musicaux ou silencieux. |
| `sentence_pause_s` | `0.8` | Une pause plus longue coupe une phrase, même sans ponctuation. |

### `[ranking]`

Le LLM note chaque passage candidat sur cinq axes de 0 à 10. Ces poids déterminent le
classement final.

| Option | Défaut | Axe |
|---|---|---|
| `hook` | `0.35` | Force des 3 premières secondes. |
| `emotion` | `0.20` | Rire, surprise, tension. |
| `value` | `0.15` | Information ou idée retenue. |
| `quotability` | `0.15` | Punchline reprenable. |
| `standalone` | `0.15` | Compréhensible hors contexte. |
| `score_floor` | `6.0` | Score pondéré minimal pour retenir un clip. À monter pour être plus sélectif. |

---

## Charte créateur

Un fichier TOML par style éditorial.

```bash
cp chartes/default.toml chartes/moncreateur.toml
uv run clippey run "https://youtu.be/..." --charte chartes/moncreateur.toml
```

Toute valeur absente reprend celle du défaut : une charte peut ne contenir que les
différences.

### Identité

| Option | Défaut | Rôle |
|---|---|---|
| `creator` | `"default"` | Nom de la charte, repris dans `manifest.json`. |
| `language` | `"fr"` | Langue de la transcription et des légendes. |
| `tone` | `"direct, énergique, sans clickbait mensonger"` | Phrase libre injectée dans les prompts. Levier principal sur la personnalité des titres. |

### `[clips]`

| Option | Défaut | Rôle |
|---|---|---|
| `duration_min_s` | `10` | En dessous, le passage est rejeté. |
| `duration_target_s` | `40` | Durée visée, annoncée au LLM. |
| `duration_max_s` | `75` | Plafond dur. |
| `max_clips` | `5` | Nombre maximum de clips par vidéo. Le LLM en rend moins si la vidéo ne s'y prête pas. |
| `tail_s` | `1.0` | Silence total après le dernier mot : images réelles si la source en a, sinon dernière image gelée. |
| `caption_max_chars` | `150` | Longueur maximale de la légende assemblée (titre + description + hashtags). Imposée au prompt et en code. |

### `[captions]`

| Option | Défaut | Rôle |
|---|---|---|
| `style` | `"karaoke"` | Mot en cours surligné, les autres en blanc. |
| `font` | `"Anton"` | Police cherchée dans `fonts_dir`. Déposer un `.ttf` dans `fonts/` pour en utiliser une autre. |
| `font_size` | `110` | Taille en pixels, base 1080×1920. |
| `primary_color` | `&H00FFFFFF` | Mots déjà prononcés. Format ASS `&HAABBGGRR` : alpha, bleu, vert, rouge — pas RVB. |
| `highlight_color` | `&H0000D7FF` | Mot en cours. |
| `outline_color` | `&H00000000` | Contour. |
| `outline` | `7` | Épaisseur du contour. Valeur haute pour rester lisible sur fond clair. |
| `shadow` | `3` | Ombre portée. |
| `margin_v` | `640` | Distance depuis le bas. Le défaut place le texte au-dessus de l'interface des applications mobiles. |
| `max_words_per_line` | `4` | Au-delà, la ligne devient illisible sur mobile. |
| `uppercase` | `true` | Texte en capitales. |
| `min_word_confidence` | `0.4` | Une ligne dont la confiance moyenne est inférieure n'est pas affichée. |

### `[hook]`

Phrase courte affichée en haut du clip dès la première image.

| Option | Défaut | Rôle |
|---|---|---|
| `enabled` | `true` | Affiche l'accroche. |
| `duration_s` | `2.5` | Durée d'affichage. |
| `font_size` | `84` | Taille en pixels. |
| `margin_v` | `320` | Distance depuis le haut. |

### `[reframe]`

| Option | Défaut | Rôle |
|---|---|---|
| `mode` | `"face"` | `face` : le cadre suit le visage dominant, recalculé à chaque changement de plan, avec une hystérésis de 6 % de la largeur. `center` : cadrage centré fixe. |

### `[hashtags]`

| Option | Défaut | Rôle |
|---|---|---|
| `base` | `["fyp", "pourtoi"]` | Ajoutés en tête, avant ceux proposés par le LLM. |
| `banned_words` | `[]` | Tags filtrés quelle que soit la réponse du LLM. |

Le total est plafonné à 12 tags. `caption_max_chars` peut en retirer depuis la fin.

---

## Invalidation

Chaque étape mémorise une empreinte des réglages dont elle dépend. Modifier un réglage
invalide l'étape correspondante et toutes les suivantes.

| Réglage modifié | Étapes rejouées |
|---|---|
| `[asr]`, `language` | tout, depuis la transcription |
| `[clips]`, `[ranking]`, `tone` | `select` → `package` |
| `[captions]`, `[hook]`, `[reframe]` | `compose` → `package` |
| `[hashtags]`, `caption_max_chars` | `caption`, `package` |

Le cache LLM (`data/<video_id>/llm_cache/`) opère en dessous : un appel identique est
resservi depuis le disque même lorsque l'étape est rejouée.
