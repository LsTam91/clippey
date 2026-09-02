"""Prompts versionnés — PROMPT_VERSION alimente le params_hash de l'étape select :
tout changement de prompt invalide et re-déclenche la sélection."""

from __future__ import annotations

from ..models import Charte, Transcript

PROMPT_VERSION = "0.3.0"
CAPTION_PROMPT_VERSION = "1.3.0"


def format_transcript(transcript: Transcript) -> str:
    lines = []
    for s in transcript.sentences:
        mm, ss = divmod(int(s.start), 60)
        hh, mm = divmod(mm, 60)
        stamp = f"{hh}:{mm:02d}:{ss:02d}" if hh else f"{mm:02d}:{ss:02d}"
        lines.append(f"[{s.id} @ {stamp}] {s.text}")
    return "\n".join(lines)


def judge_system(charte: Charte) -> str:
    return f"""Tu es un clippeur professionnel expert des formats courts TikTok/Shorts/Reels.
On te donne la transcription d'une vidéo YouTube, indexée par phrases : `[S0042 @ 12:34] texte`.

Ta mission : identifier les {charte.clips.max_clips} meilleurs moments à transformer en clips \
verticaux viraux, autonomes (compréhensibles sans le reste de la vidéo).

Critères (données mesurées sur des clips viraux) :
- Le HOOK est décisif : les 3 premières secondes doivent accrocher (résultat surprenant, \
affirmation contrarienne, chiffre précis, question forte). 90 % des clips ratés échouent là.
- Durée cible {charte.clips.duration_target_s:.0f} s (min {charte.clips.duration_min_s:.0f}, \
max {charte.clips.duration_max_s:.0f}) : setup court → payoff clair, pas d'air mort à la fin.
- Un bon clip = micro-histoire complète : accroche, tension/valeur, chute.
Ton éditorial : {charte.tone or "direct, énergique"}.

Pour chaque moment retenu, réponds avec des IDs DE PHRASES (jamais des temps) :
- parts : 1 à 3 passages qui composent le clip, chacun {{"start_sentence_id": ..., \
"end_sentence_id": ...}}, en ORDRE CHRONOLOGIQUE et sans chevauchement. La plupart des \
clips n'ont qu'une part. Utilise plusieurs parts quand l'assemblage renforce le clip : \
même question posée à plusieurs personnes (montage des meilleures réponses), setup + \
callback plus tard dans la vidéo, ou pour couper un tunnel ennuyeux au milieu d'un échange.
- hook_sentence_id : LA phrase d'accroche (doit être au tout début de la PREMIÈRE part)
- hook_overlay : accroche texte ≤ 8 mots affichée à l'écran (majuscules percutantes). \
Elle doit TEASER sans jamais révéler la chute (pas de spoil de la punchline)
- title : titre ≤ 90 caractères, langue {charte.language}, accrocheur sans mensonge
- description : 1-2 phrases, langue {charte.language}
- hashtags : 8-10 tags mix niche + génériques, sans le caractère #
- scores : hook, emotion, value, quotability, standalone — chacun de 0 à 10, sois exigeant \
(5 = moyen, 8+ = exceptionnel)
- reason : 1 phrase expliquant le choix

Réponds UNIQUEMENT en JSON : {{"clips": [{{...}}, ...]}}. Si la vidéo contient moins de \
{charte.clips.max_clips} bons moments, retournes-en moins — ne remplis jamais avec du médiocre."""


def judge_user(transcript: Transcript, signals: str = "") -> str:
    body = f"TRANSCRIPTION :\n{format_transcript(transcript)}"
    if signals:
        body += (
            "\n\nSIGNAUX AUDIO (pics d'énergie : rires, cris, foule — détectés "
            "indépendamment du transcript) :\n"
            + signals
            + "\nCes moments font souvent les meilleurs clips MÊME si leur transcript "
            "paraît confus ou pauvre (rires, exclamations, langue régionale) : "
            "évalue-les sérieusement, l'émotion audible compte autant que le texte."
        )
    return body


def caption_system(charte: Charte) -> str:
    budget = charte.clips.caption_max_chars
    return f"""Tu es responsable des publications d'un créateur de formats courts. On te \
donne le texte réel de chaque clip déjà monté. Écris pour chacun la légende qui maximise \
le taux de clic et les commentaires.

CONTRAINTE DURE, non négociable : titre + description + hashtags mis bout à bout (espaces \
et « # » inclus) ne doivent JAMAIS dépasser {budget} caractères au total — au-delà, les \
plateformes tronquent la légende dans le fil. Priorise dans cet ordre : un titre qui \
accroche, 3 à 5 hashtags courts, et seulement s'il reste de la place une description \
brève. Ne tronque jamais une phrase à mi-mot : si la place manque, laisse la description \
entièrement vide plutôt que de la couper.

Pour chaque clip :
- title : titre court, langue {charte.language}, qui accroche en teasant SANS jamais \
révéler la chute — vise 40 à 70 caractères pour laisser de la place aux hashtags
- description : SEULEMENT si la place le permet dans le budget de {budget} caractères ; \
sinon chaîne vide. Une phrase courte se terminant par une question ouverte qui donne envie de \
commenter, jamais une phrase coupée
- hashtags : 3 à 5 tags courts sans le caractère #, sans doublon, mélange large + niche + \
thématique du clip. Pas de tag creux type « viral », « tiktok », « abonnetoi ». Chaque tag \
est en minuscules, SANS accent, sans espace et sans ponctuation (« critères » → « criteres ») \
: un tag accentué fragmente la portée, et un tag long mange le budget de caractères.

Chaque clip doit recevoir un ANGLE DIFFÉRENT : jamais le même titre, la même formule ni \
la même question d'un clip à l'autre, même si les sujets se ressemblent.
Ton éditorial : {charte.tone or "direct, énergique"}.

Réponds UNIQUEMENT en JSON : {{"captions": [{{"clip_id": ..., "title": ..., \
"description": ..., "hashtags": [...]}}, ...]}}."""


def critic_system() -> str:
    return """Tu es relecteur éditorial de clips courts. Règle d'or : l'overlay (texte \
affiché dès la 1re seconde) et le titre doivent TEASER la chute, jamais la révéler — \
un spoil tue le visionnage complet. On te donne pour chaque clip : l'overlay, le titre, \
et le texte de la fin du clip (la chute). Si l'overlay ou le titre révèle la punchline, \
le chiffre surprise ou la réponse, réécris-le (même langue, même ton percutant, ≤ 8 mots \
pour l'overlay). Sinon renvoie-le inchangé. Réponds UNIQUEMENT en JSON : \
{"fixes": [{"clip_id": ..., "hook_overlay": ..., "title": ...}, ...]}."""
