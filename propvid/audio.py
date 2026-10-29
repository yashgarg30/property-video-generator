"""Audio: royalty-free background music synthesised in code + optional offline TTS narration.

The music is generated from sine waves at runtime, so there is no licensing question.
Narration uses the OS's built-in offline voice: Windows (System.Speech via PowerShell),
macOS (`say`), Linux (espeak-ng / espeak), or pyttsx3 if installed. If none exists the video still renders with
music + on-screen captions, and a note says narration was skipped.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from typing import List, Optional, Tuple

import numpy as np

SR = 44100


# ---------------------------------------------------------------- music
def _note(freq: float, dur: float, amp: float) -> np.ndarray:
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    wave_ = (np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(2 * np.pi * 2 * freq * t)
             + 0.1 * np.sin(2 * np.pi * 3 * freq * t))
    env = np.minimum(1, t / 0.4) * np.minimum(1, (dur - t) / 0.6)  # soft attack/release
    return amp * wave_ * np.clip(env, 0, 1)


def make_music(duration: float) -> np.ndarray:
    """Calm I–V–vi–IV pad with a light arpeggio. Returns float32 mono in [-1, 1]."""
    chords = [(261.63, 329.63, 392.00), (196.00, 246.94, 293.66),
              (220.00, 261.63, 329.63), (174.61, 220.00, 261.63)]
    bar = 2.4
    n = int(SR * duration)
    out = np.zeros(n + SR * 4, dtype=np.float64)
    pos, i = 0, 0
    while pos < n:
        chord = chords[i % 4]
        for f in chord:
            seg = _note(f / 2, bar + 0.6, 0.12)
            out[pos:pos + len(seg)] += seg
        step = bar / 6
        for k in range(6):
            f = chord[k % 3] * (2 if k >= 3 else 1)
            seg = _note(f, step * 1.6, 0.05)
            s = pos + int(k * step * SR)
            out[s:s + len(seg)] += seg
        pos += int(bar * SR)
        i += 1
    out = out[:n]
    fade = int(SR * 1.5)
    out[:fade] *= np.linspace(0, 1, fade)
    out[-fade:] *= np.linspace(1, 0, fade)
    peak = np.max(np.abs(out)) or 1.0
    return (out / peak * 0.9).astype(np.float32)


# ---------------------------------------------------------------- TTS
def detect_tts() -> Optional[str]:
    """Pick an offline voice engine that ships with the OS where possible."""
    if os.name == "nt" and shutil.which("powershell"):
        return "windows"                       # built-in Windows voice (System.Speech), no install
    if sys.platform == "darwin" and shutil.which("say"):
        return "say"                           # built-in macOS voice
    for exe in ("espeak-ng", "espeak"):        # Linux
        if shutil.which(exe):
            return exe
    try:
        import pyttsx3  # noqa: F401
        return "pyttsx3"
    except Exception:
        return None


def _trim_silence(clip: np.ndarray, thresh: float = 0.01) -> np.ndarray:
    """Cut leading/trailing silence that engines add, so lines fit their scenes."""
    loud = np.where(np.abs(clip) > thresh)[0]
    if loud.size == 0:
        return clip[:0]
    pad = int(SR * 0.05)
    return clip[max(0, loud[0] - pad): loud[-1] + pad]


def speakable(text: str) -> str:
    """Make listing text read naturally aloud (symbols/abbreviations TTS engines mangle)."""
    text = re.sub(r"(?:₹|Rs\.?|INR)\s*([\d.,]+\s*(?:Crore|Cr|Lakh|Lac|L|K)?)", r"\1 rupees", text, flags=re.I)
    text = re.sub(r"\bBHK\b", "B H K", text)
    text = re.sub(r"\bsq\.?\s*ft\b", "square feet", text, flags=re.I)
    text = re.sub(r"\S+@\S+\.\w+", "", text)                    # emails read badly; they stay on screen
    text = re.sub(r"\bor\s*(?=[.,]|$)|(?<=Contact)\s*or\b", "", text)  # tidy "a or <email>" leftovers
    text = text.replace("+91", "plus 91,")
    # phone numbers: read digit by digit ("9 8 7 6 5"), not as "ninety-eight thousand…"
    text = re.sub(r"\d[\d ]{6,}\d", lambda m: " ".join(m.group(0).replace(" ", "")), text)
    text = re.sub(r"\s{2,}", " ", text).replace(" .", ".")
    return text.replace("&", " and ").strip()


_PS = ("$ErrorActionPreference='Stop';Add-Type -AssemblyName System.Speech;"
       "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;$s.Rate=1;$s.Volume=100;"
       "$s.SetOutputToWaveFile('{out}');$s.Speak((Get-Content -Raw -Encoding UTF8 '{txt}'));$s.Dispose()")


def synth_line(text: str, engine: str, workdir: str, idx: int) -> Optional[np.ndarray]:
    """Speak one line to a float32 mono array at SR, or None on failure."""
    text = speakable(text)
    out = os.path.join(workdir, f"line_{idx}.wav")
    try:
        if engine == "windows":
            txt = os.path.join(workdir, f"line_{idx}.txt")
            with open(txt, "w", encoding="utf-8") as fh:
                fh.write(text)
            q = lambda p: p.replace("'", "''")
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            _PS.format(out=q(out), txt=q(txt))],
                           check=True, capture_output=True, timeout=60)
        elif engine in ("espeak-ng", "espeak"):
            subprocess.run([engine, "-s", "150", "-v", "en-us", "-w", out, text],
                           check=True, capture_output=True, timeout=60)
        elif engine == "say":
            out = out.replace(".wav", ".aiff")
            subprocess.run(["say", "-o", out, text], check=True, capture_output=True, timeout=60)
        elif engine == "pyttsx3":
            import pyttsx3
            eng = pyttsx3.init()
            eng.setProperty("rate", 165)
            eng.save_to_file(text, out)
            eng.runAndWait()
        clip = _trim_silence(load_audio(out))
        peak = float(np.max(np.abs(clip))) if clip.size else 0.0
        return clip / peak * 0.9 if peak > 0 else None   # normalise voice loudness
    except Exception:
        return None


def load_audio(path: str) -> np.ndarray:
    """Decode any audio file to float32 mono @ SR using ffmpeg."""
    from .render import ffmpeg_exe
    raw = subprocess.run([ffmpeg_exe(), "-v", "error", "-i", path, "-f", "f32le", "-ac", "1",
                          "-ar", str(SR), "-"], check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def narrate(lines: List[str], enabled: bool) -> Tuple[List[Optional[np.ndarray]], str]:
    """Return per-scene narration clips (None where no line / no TTS) and a status note."""
    if not enabled:
        return [None] * len(lines), "Narration disabled."
    engine = detect_tts()
    if not engine:
        return [None] * len(lines), ("No offline voice engine found — video uses music + captions only. "
                                     "(Windows/macOS have one built in; on Linux install espeak-ng.)")
    clips = []
    with tempfile.TemporaryDirectory() as td:
        for i, line in enumerate(lines):
            clips.append(synth_line(line, engine, td, i) if line else None)
    ok = sum(c is not None for c in clips)
    want = sum(1 for l in lines if l)
    if ok == 0 and want:
        return clips, f"Voice engine '{engine}' failed — video uses music + captions only."
    return clips, f"Narration by {engine}: {ok}/{want} lines."


# ---------------------------------------------------------------- mixing
def _moving_avg(x: np.ndarray, width: int) -> np.ndarray:
    c = np.cumsum(np.concatenate([[0.0], x]))
    half = width // 2
    idx = np.arange(len(x))
    lo, hi = np.clip(idx - half, 0, len(x)), np.clip(idx + half, 0, len(x))
    return ((c[hi] - c[lo]) / np.maximum(hi - lo, 1)).astype(np.float32)


def mix(duration: float, starts: List[float], clips: List[Optional[np.ndarray]],
        music: bool, path: str) -> None:
    """Mix music (ducked under speech) and narration, write 16-bit stereo WAV."""
    n = int(SR * duration)
    voice = np.zeros(n, dtype=np.float32)
    next_free = 0                                   # sample index where the previous line ended
    for st, clip in zip(starts, clips):
        if clip is None:
            continue
        s = max(int((st + 0.35) * SR), next_free + int(SR * 0.15))   # never talk over the last line
        e = min(n, s + len(clip))
        if s < n:
            voice[s:e] = clip[: e - s]
            next_free = e
    if music:
        bg = make_music(duration)[:n]
        speaking = _moving_avg((np.abs(voice) > 0.02).astype(np.float32), int(SR * 0.3))
        duck = 1.0 - 0.7 * np.clip(speaking * 4, 0, 1)        # music dips under the voice
        mixdown = bg * 0.9 * duck + voice
    else:
        mixdown = voice
    peak = float(np.max(np.abs(mixdown))) or 1.0
    mixdown = mixdown / peak * 0.95                          # loud and clear, no clipping
    pcm = (np.clip(mixdown, -1, 1) * 32767).astype(np.int16)
    stereo = np.repeat(pcm[:, None], 2, axis=1)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(stereo.tobytes())