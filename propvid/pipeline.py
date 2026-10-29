"""End-to-end pipeline: Listing → validated input → script → audio → MP4 (+ thumbnail + script.json)."""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .audio import SR, mix, narrate
from .listing import Listing, ListingError
from .render import RenderError, TRANSITION, render_video, timeline
from .script import Script, build_template_script

BASE_DUR = {"title": 4.2, "feature": 3.6, "gallery": 3.2, "price": 3.6, "cta": 4.8}
MAX_TOTAL = 45.0


@dataclass
class Options:
    fmt: str = "landscape"            # landscape | portrait | square
    narration: bool = True
    music: bool = True
    accent: str = "#E8632B"
    fps: int = 25


@dataclass
class Result:
    video: str
    thumbnail: str
    script_json: str
    duration: float
    script: Script
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "property"


def generate(listing: Listing, out_path: Optional[str] = None, opts: Optional[Options] = None,
             progress: Optional[Callable[[float], None]] = None) -> Result:
    """Raises ListingError (bad input) or RenderError (environment); both have user-facing messages."""
    opts = opts or Options()
    errors, warnings, images = listing.validate()
    if errors:
        raise ListingError("Cannot create video:\n  - " + "\n  - ".join(errors))

    out_path = out_path or os.path.join("output", f"{slugify(listing.name)}.mp4")
    stem = os.path.splitext(out_path)[0]

    # 1) Script & captions
    script = build_template_script(listing, images)
    notes = list(script.notes)

    # 2) Narration (per scene, so we can time scenes to the speech)
    clips, tts_note = narrate([s.narration for s in script.scenes], opts.narration)
    notes.append(tts_note)

    # 3) Scene durations: base length, stretched if narration is longer
    durations = []
    for s, clip in zip(script.scenes, clips):
        d = BASE_DUR.get(s.kind, 3.5)
        if clip is not None:
            d = max(d, len(clip) / SR + 0.35 + TRANSITION + 0.3)
        durations.append(round(d, 2))
    _, total = timeline(durations)
    if total > MAX_TOTAL:  # keep it share-friendly, but NEVER cut a scene shorter than its voice line
        scale = MAX_TOTAL / total
        floors = [(len(c) / SR + 0.35 + TRANSITION + 0.15) if c is not None else 2.5 for c in clips]
        durations = [round(max(f, d * scale), 2) for d, f in zip(durations, floors)]
        notes.append("Silent padding trimmed to keep the video short.")
    starts, total = timeline(durations)

    # 4) Audio + video
    with tempfile.TemporaryDirectory() as td:
        audio_path = None
        if opts.music or any(c is not None for c in clips):
            audio_path = os.path.join(td, "mix.wav")
            mix(total, starts, clips, opts.music, audio_path)
        thumb = stem + "_thumb.jpg"
        total = render_video(script.scenes, durations, audio_path, out_path, fmt=opts.fmt,
                             fps=opts.fps, accent_hex=opts.accent,
                             progress=progress, thumb_path=thumb)

    # 5) Save the script / captions for review (how we "check the AI output")
    script_json = stem + "_script.json"
    with open(script_json, "w", encoding="utf-8") as fh:
        json.dump({"input": listing.to_dict(), "duration_sec": round(total, 2),
                   "scene_durations": durations, "warnings": warnings, "notes": notes,
                   **script.to_dict()}, fh, indent=2, ensure_ascii=False)

    return Result(out_path, thumb, script_json, total, script, warnings, notes)


__all__ = ["generate", "Options", "Result", "ListingError", "RenderError"]