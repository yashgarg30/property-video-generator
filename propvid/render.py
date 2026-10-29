"""Video rendering: Pillow draws every frame (Ken Burns motion, crossfades, text overlays),
frames are piped straight into ffmpeg which encodes H.264 MP4 with the mixed audio track."""
from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageOps

FORMATS = {"landscape": (1280, 720), "portrait": (720, 1280), "square": (1080, 1080)}
OVERSCAN = 1.12          # how much bigger than the frame the image is, for zoom/pan room
TRANSITION = 0.6         # crossfade seconds
TEXT_FADE = 0.5          # caption fade-in seconds


class RenderError(Exception):
    """User-facing rendering problem (e.g. ffmpeg missing)."""


# ---------------------------------------------------------------- ffmpeg discovery
@lru_cache(maxsize=1)
def ffmpeg_exe() -> str:
    exe = os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")
    if not exe:
        try:
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            exe = None
    if not exe:
        raise RenderError("ffmpeg not found. Install it (e.g. `sudo apt install ffmpeg`, "
                          "`brew install ffmpeg`, or `pip install imageio-ffmpeg`).")
    return exe


@lru_cache(maxsize=1)
def video_codec() -> List[str]:
    try:
        enc = subprocess.run([ffmpeg_exe(), "-hide_banner", "-encoders"],
                             capture_output=True, text=True, timeout=30).stdout
    except Exception:
        enc = ""
    if "libx264" in enc:
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21"]
    return ["-c:v", "mpeg4", "-q:v", "3"]


# ---------------------------------------------------------------- fonts
_BOLD = ["DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/Library/Fonts/Arial Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
         "C:/Windows/Fonts/arialbd.ttf", "LiberationSans-Bold.ttf"]
_REG = ["DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf", "LiberationSans-Regular.ttf"]


@lru_cache(maxsize=64)
def font(size: int, bold: bool = True) -> ImageFont.ImageFont:
    for cand in (_BOLD if bold else _REG):
        try:
            return ImageFont.truetype(cand, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def wrap(draw: ImageDraw.ImageDraw, text: str, size: int, bold: bool, max_w: int) -> List[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font(size, bold)) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit(draw, text, max_w, max_size, min_size, bold=True, max_lines=2) -> Tuple[int, List[str]]:
    """Largest font size where text wraps into <= max_lines lines within max_w."""
    size = max_size
    while size > min_size:
        lines = wrap(draw, text, size, bold, max_w)
        if len(lines) <= max_lines and all(draw.textlength(l, font=font(size, bold)) <= max_w for l in lines):
            return size, lines
        size -= 2
    lines = wrap(draw, text, min_size, bold, max_w)
    if len(lines) > max_lines:  # truncate gracefully rather than overflow
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,;") + "…"
    return min_size, lines


def hex_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (232, 99, 43)


# ---------------------------------------------------------------- image prep
def load_cover(path: str, W: int, H: int) -> Image.Image:
    """Open, fix EXIF rotation, and center-crop to cover (W*OVERSCAN, H*OVERSCAN)."""
    bw, bh = int(W * OVERSCAN), int(H * OVERSCAN)
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        return ImageOps.fit(im, (bw, bh), Image.LANCZOS, centering=(0.5, 0.5))


def kenburns(base: Image.Image, W: int, H: int, p: float, zoom_in: bool, pan: int) -> Image.Image:
    p = p * p * (3 - 2 * p)                     # smoothstep easing
    z = p if zoom_in else 1 - p                 # 0 → widest, 1 → tightest
    bw, bh = base.size
    cw = bw - (bw - W) * z
    ch = bh - (bh - H) * z
    dx = (bw - cw) / 2 + pan * (p - 0.5) * (bw - cw) * 0.8
    dy = (bh - ch) / 2
    dx = max(0, min(bw - cw, dx))
    return base.resize((W, H), Image.BILINEAR, box=(dx, dy, dx + cw, dy + ch))


# ---------------------------------------------------------------- overlays
def _shadow_text(d: ImageDraw.ImageDraw, xy, text, f, fill=(255, 255, 255, 255), anchor="la"):
    x, y = xy
    d.text((x + 2, y + 3), text, font=f, fill=(0, 0, 0, 150), anchor=anchor)
    d.text((x, y), text, font=f, fill=fill, anchor=anchor)


def _vgradient(W, H, top_alpha, bottom_alpha, start=0.0) -> Image.Image:
    g = Image.new("L", (1, H))
    for y in range(H):
        t = max(0.0, (y / H - start) / (1 - start)) if start < 1 else 0
        g.putpixel((0, y), int(top_alpha + (bottom_alpha - top_alpha) * t))
    alpha = g.resize((W, H))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.putalpha(alpha)
    return layer


def build_overlay(scene, W, H, accent, idx: int, total_feat: int) -> Image.Image:
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    m = int(min(W, H) * 0.07)                 # margin
    unit = min(W, H) / 720                    # scale factor for font sizes
    A = accent + (255,)

    if scene.kind == "title":
        ov = Image.alpha_composite(ov, _vgradient(W, H, 30, 215, 0.25))
        d = ImageDraw.Draw(ov)
        size, lines = fit(d, scene.caption, W - 2 * m, int(64 * unit), int(30 * unit), max_lines=2)
        sub_f = font(int(26 * unit), False)
        line_h = int(size * 1.18)
        block = line_h * len(lines) + (int(46 * unit) if scene.sub else 0)
        y = H - m - block
        d.rectangle([m, y - int(22 * unit), m + int(90 * unit), y - int(14 * unit)], fill=A)
        for ln in lines:
            _shadow_text(d, (m, y), ln, font(size))
            y += line_h
        if scene.sub:
            _shadow_text(d, (m, y + int(8 * unit)), scene.sub, sub_f, fill=(235, 235, 235, 255))

    elif scene.kind in ("feature", "gallery"):
        ov = Image.alpha_composite(ov, _vgradient(W, H, 0, 200, 0.55))
        d = ImageDraw.Draw(ov)
        size, lines = fit(d, scene.caption, W - 2 * m - int(24 * unit), int(48 * unit), int(24 * unit))
        line_h = int(size * 1.2)
        y = H - m - line_h * len(lines)
        d.rectangle([m, y - int(4 * unit), m + int(8 * unit), H - m + int(2 * unit)], fill=A)
        for ln in lines:
            _shadow_text(d, (m + int(24 * unit), y), ln, font(size))
            y += line_h
        if scene.kind == "feature" and total_feat:
            tag = f"{idx:02d} / {total_feat:02d}"
            _shadow_text(d, (W - m, m), tag, font(int(22 * unit)), fill=(255, 255, 255, 230), anchor="ra")
        elif scene.sub:
            _shadow_text(d, (m + int(24 * unit), m), scene.sub, font(int(22 * unit), False))

    elif scene.kind == "price":
        ov = Image.alpha_composite(ov, _vgradient(W, H, 60, 190, 0.0))
        d = ImageDraw.Draw(ov)
        size, lines = fit(d, scene.caption, int(W * 0.8), int(72 * unit), int(30 * unit))
        lab_f = font(int(24 * unit))
        line_h = int(size * 1.18)
        bh = line_h * len(lines) + int(70 * unit)
        bw = max(d.textlength(l, font=font(size)) for l in lines) + int(80 * unit)
        x0, y0 = (W - bw) / 2, (H - bh) / 2
        d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=int(18 * unit), fill=(15, 20, 35, 200))
        d.rectangle([x0, y0, x0 + bw, y0 + int(6 * unit)], fill=A)
        d.text((W / 2, y0 + int(22 * unit)), scene.sub.upper(), font=lab_f, fill=A, anchor="ma")
        y = y0 + int(58 * unit)
        for ln in lines:
            d.text((W / 2, y), ln, font=font(size), fill=(255, 255, 255, 255), anchor="ma")
            y += line_h

    elif scene.kind == "cta":
        ov = Image.new("RGBA", (W, H), (10, 14, 28, 185))
        d = ImageDraw.Draw(ov)
        size, lines = fit(d, scene.caption, W - 2 * m, int(58 * unit), int(28 * unit))
        line_h = int(size * 1.2)
        sub_size, sub_lines = (fit(d, scene.sub, W - 2 * m, int(32 * unit), int(18 * unit), bold=False)
                               if scene.sub else (0, []))
        block = line_h * len(lines) + (int(sub_size * 1.3) * len(sub_lines) + int(40 * unit) if sub_lines else 0)
        y = (H - block) / 2
        for ln in lines:
            d.text((W / 2, y), ln, font=font(size), fill=(255, 255, 255, 255), anchor="ma")
            y += line_h
        if sub_lines:
            y += int(16 * unit)
            pad = int(18 * unit)
            sw = max(d.textlength(l, font=font(sub_size, False)) for l in sub_lines)
            sh = int(sub_size * 1.3) * len(sub_lines)
            d.rounded_rectangle([W / 2 - sw / 2 - pad, y - pad / 2, W / 2 + sw / 2 + pad, y + sh + pad / 2],
                                radius=int(12 * unit), fill=A)
            for ln in sub_lines:
                d.text((W / 2, y), ln, font=font(sub_size, False), fill=(255, 255, 255, 255), anchor="ma")
                y += int(sub_size * 1.3)
    return ov


# ---------------------------------------------------------------- timeline + encode
def timeline(durations: List[float]) -> Tuple[List[float], float]:
    starts, t = [], 0.0
    for i, d in enumerate(durations):
        starts.append(t)
        t += d - (TRANSITION if i < len(durations) - 1 else 0)
    return starts, t


def render_video(scenes, durations: List[float], audio_path: Optional[str], out_path: str,
                 fmt: str = "landscape", fps: int = 25, accent_hex: str = "#E8632B",
                 progress=None, thumb_path: Optional[str] = None) -> float:
    W, H = FORMATS.get(fmt, FORMATS["landscape"])
    accent = hex_rgb(accent_hex)
    starts, total = timeline(durations)

    feat_total = sum(1 for s in scenes if s.kind == "feature")
    bases, overlays, feat_i = [], [], 0
    for s in scenes:
        bases.append(load_cover(s.image, W, H))
        if s.kind == "feature":
            feat_i += 1
        overlays.append(build_overlay(s, W, H, accent, feat_i, feat_total))

    def scene_frame(i: int, t: float) -> Image.Image:
        local = t - starts[i]
        p = min(1.0, max(0.0, local / durations[i]))
        img = kenburns(bases[i], W, H, p, scenes[i].zoom_in, pan=1 if i % 2 else -1).convert("RGBA")
        withtext = Image.alpha_composite(img, overlays[i])
        a = min(1.0, max(0.0, (local - 0.15) / TEXT_FADE)) if i > 0 else min(1.0, local / 0.8)
        return withtext if a >= 1 else Image.blend(img, withtext, a)

    cmd = [ffmpeg_exe(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(fps), "-i", "-"]
    if audio_path:
        cmd += ["-i", audio_path]
    cmd += video_codec() + ["-pix_fmt", "yuv420p"]
    if audio_path:
        cmd += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += ["-movflags", "+faststart", out_path]

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    n_frames = int(round(total * fps))
    try:
        for f in range(n_frames):
            t = f / fps
            active = [i for i in range(len(scenes)) if starts[i] <= t < starts[i] + durations[i]]
            if not active:
                active = [len(scenes) - 1]
            frame = scene_frame(active[0], t)
            if len(active) > 1:  # crossfade into next scene
                nxt = active[1]
                frame = Image.blend(frame, scene_frame(nxt, t), (t - starts[nxt]) / TRANSITION)
            # gentle fade to black on the last 0.5s
            if t > total - 0.5:
                frame = Image.blend(Image.new("RGBA", (W, H), (0, 0, 0, 255)), frame, max(0.0, (total - t) / 0.5))
            if thumb_path and f == int(1.6 * fps):
                frame.convert("RGB").save(thumb_path, quality=88)
            proc.stdin.write(frame.convert("RGB").tobytes())
            if progress and f % fps == 0:
                progress(f / n_frames)
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            raise RenderError(f"ffmpeg failed: {err.strip()[-500:]}")
    except BrokenPipeError:
        err = proc.stderr.read().decode(errors="replace")
        proc.wait()
        raise RenderError(f"ffmpeg stopped unexpectedly: {err.strip()[-500:]}")
    if progress:
        progress(1.0)
    return total