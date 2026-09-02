"""Paquet prêt-à-poster : manifest.json (contrat machine) + review.html, la galerie
locale où l'on relit les clips et leur légende avant de les publier soi-même."""

from __future__ import annotations

import datetime
import html

from .models import CaptionSet, ClipCaption, ClipManifestEntry, Manifest, Selection, VideoMeta
from .pipeline import Context, write_json_atomic


def step_package(ctx: Context) -> None:
    selection = Selection.model_validate_json(ctx.paths["selection"].read_text())
    meta = VideoMeta.model_validate_json(ctx.paths["meta"].read_text())
    captions = _load_captions(ctx)

    entries = []
    for clip in selection.clips:
        caption = captions.get(clip.id)
        title = caption.title if caption else clip.title
        description = caption.description if caption else clip.description
        hashtags = caption.hashtags if caption else clip.hashtags
        entries.append(
            ClipManifestEntry(
                clip_id=clip.id,
                file=f"clips/{clip.id}.mp4",
                title=title,
                description=description,
                hashtags=hashtags,
                duration_s=round(clip.total_duration, 1),
                weighted_score=clip.weighted_score,
                source_t0=clip.t0,
                source_t1=clip.t1,
            )
        )
        ctx.db.record_clip(
            clip.id,
            ctx.video_id,
            clip.t0,
            clip.t1,
            clip.weighted_score,
            title,
            clip.file_path,
        )

    manifest = Manifest(
        video_id=ctx.video_id,
        source_url=meta.url,
        source_title=meta.title,
        charte=ctx.charte.creator,
        generated_at=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        total_cost_eur=round(ctx.db.video_cost_eur(ctx.video_id), 4),
        clips=entries,
    )
    write_json_atomic(ctx.paths["manifest"], manifest.model_dump_json(indent=1))
    ctx.paths["review"].write_text(_review_html(manifest), encoding="utf-8")
    print(
        f"       {len(entries)} clips | coût {manifest.total_cost_eur:.3f} € | "
        f"review : {ctx.paths['review']}"
    )


def _load_captions(ctx: Context) -> dict[str, ClipCaption]:
    if not ctx.paths["captions"].exists():
        return {}
    captions = CaptionSet.model_validate_json(ctx.paths["captions"].read_text())
    return {c.clip_id: c for c in captions.clips}


def build_caption(title: str, description: str, hashtags: list[str]) -> str:
    """Légende prête à coller : ce que l'utilisateur relit dans review.html."""
    return f"{title}\n\n{description}\n\n" + " ".join(f"#{t}" for t in hashtags)


def _review_html(m: Manifest) -> str:
    cards = []
    for c in m.clips:
        caption = build_caption(c.title, c.description, c.hashtags)
        cards.append(f"""
  <div class="card">
    <video controls preload="metadata" src="{html.escape(c.file)}"></video>
    <div class="info">
      <h2>{html.escape(c.title)}</h2>
      <p class="meta">{c.duration_s:.0f}s · score {c.weighted_score} ·
         source {_fmt(c.source_t0)}→{_fmt(c.source_t1)}</p>
      <textarea rows="6" onclick="this.select()">{html.escape(caption)}</textarea>
      <p class="rate">Noter : <code>clippey rate {c.clip_id} --stars N</code></p>
    </div>
  </div>""")
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>clippey — {html.escape(m.source_title)}</title>
<style>
 body {{ font-family: system-ui; background:#111; color:#eee; margin:2rem; }}
 h1 {{ font-size:1.2rem; }} .cost {{ color:#8f8; }}
 .card {{ display:flex; gap:1.5rem; margin:2rem 0; padding:1rem; background:#1c1c22;
         border-radius:12px; }}
 video {{ width:270px; aspect-ratio:9/16; background:#000; border-radius:8px; }}
 .info {{ flex:1; }} textarea {{ width:100%; background:#26262e; color:#eee;
         border:1px solid #444; border-radius:6px; padding:.5rem; }}
 .meta {{ color:#999; }} .rate {{ color:#777; font-size:.85rem; }}
</style></head><body>
<h1>{html.escape(m.source_title)} <span class="cost">({m.total_cost_eur:.3f} € API)</span></h1>
<p><a style="color:#8cf" href="{html.escape(m.source_url)}">{html.escape(m.source_url)}</a>
 · charte : {html.escape(m.charte)} · {m.generated_at}</p>
<p class="rate">Fichiers : <code>data/{html.escape(m.video_id)}/clips/</code> —
 cliquer une légende la sélectionne, prête à coller.</p>
{"".join(cards)}
</body></html>"""


def _fmt(t: float) -> str:
    m, s = divmod(int(t), 60)
    return f"{m}:{s:02d}"
