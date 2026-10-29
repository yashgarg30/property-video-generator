# AI Property Video Generator

Turns a property listing (name, location, price, type, features, CTA/contact) and 4–8 photos into a
**20–40 second, ready-to-share MP4** — title scene, one scene per key feature, price card and an enquiry
end card — with Ken Burns motion, crossfades, readable captions, royalty-free background music and
optional narration. No video editor needed.

```
Listing + photos ──► validate ──► script & captions ──► narration (optional) ──► timeline ──► frames ──► ffmpeg ──► MP4
                    (errors /    (template, or AI      (offline TTS, scene     (scene lengths    (Pillow)            + thumbnail
                     warnings)    rewrite + fact check)  lengths fit speech)     + transitions)                       + script.json
```

## Quick start

Requirements: **Python 3.9+**. Everything else (incl. ffmpeg) installs via pip.

```bash
pip install -r requirements.txt          # Pillow, numpy, imageio-ffmpeg (includes ffmpeg)

python app.py                            # open http://localhost:8000  — press q to stop
```
Use another port with `python app.py 8080`. Built on Python's standard library — no Flask/Streamlit needed.

## Using the web form
1. Fill in the property details (only **Property name** is required).
2. Upload 4–8 photos — upload order = scene order; the first photo is the title shot.
3. Pick options, click **Generate video** (about 15–60 s).
4. The result page shows a **video preview**, any warnings, the scene/voice-over list, and buttons to
   **Download MP4** and the **script & captions JSON**.

For a one-click demo, leave everything empty, tick **"Use sample photos/details"** and click Generate.

| Field / option | Notes |
|---|---|
| Property name * | Video title |
| Property type, Location | Shown under the title and in the opening voice-over |
| Price | Price card scene (skipped if empty) |
| Key features | One per line; first 5 become feature scenes |
| Call to action, Contact | End card (defaults to "Enquire today") |
| Property photos | JPG / PNG / WebP, 4–8 recommended, min 320×240 |
| Video format | landscape 1280×720 (web/YouTube), portrait 720×1280 (Reels/Shorts/WhatsApp status), square 1080×1080 (feed) |
| Background music / Narration | Toggle audio parts |

Sample listing used by the demo checkbox: `sample_data/listing.json` (+ `sample_data/images/`).
Generated videos are saved under `runs/<id>/`.

## Sample video
Run the app, tick **"Use sample photos/details"**, click **Generate video**, then **Download MP4**
(≈26 s, 8 scenes). Each video is saved with a `_script.json` (input, scenes, captions, voice-over,
warnings) and a `_thumb.jpg` under `runs/<id>/`.

## How it works / key decisions
- **Scene plan (template logic):** Title (photo 1, name + type + location) → up to 5 feature scenes
  (one photo + one feature each, numbered `01/05`) → price card → CTA end card. Photo 1 is the hero shot.
  Matches the brief's "opening title, 3–5 feature scenes, final enquiry prompt".
- **Only supplied facts:** captions are the input text verbatim; narration is the input text plus fixed
  connector phrases ("Introducing…", "Next:", "Available at…"). Nothing is inferred (no sq ft, no
  "near metro"). Unit tests assert this via `fact_check()`.
- **Timing:** scene length = base length, stretched to fit its narration line when TTS is on; total
  capped at 45 s.
- **Visuals:** images are EXIF-rotated and cover-cropped (no stretching), slow zoom/pan, 0.6 s crossfades,
  caption fade-in, dark gradients behind text for readability on any photo, text auto-sized/wrapped so
  long features never overflow. Fonts fall back across Linux/macOS/Windows.
- **Audio:** background music is **synthesised in code** (soft chord pad + arpeggio) — royalty-free by
  construction. It is automatically ducked under narration.
- **Rendering:** frames drawn with Pillow and piped straight into ffmpeg (H.264 + AAC, `yuv420p`,
  `faststart`) → plays on WhatsApp, Instagram, browsers, phones.

## Error handling
| Situation | Behaviour |
|---|---|
| No name / no readable images | Stops with a clear message in a red box on the form; entered fields are kept |
| Missing location, price, type, features, CTA | Warning; that element/scene is skipped, generic "Enquire today" end card |
| Missing, corrupt, unsupported or tiny (<320×240) image | Skipped with a warning naming the file |
| Fewer than 4 images | Warning; photos reused with different zoom direction |
| More than 8 images / more than 5 features | First 8 / first 5 used, warning shown |
| Upload over 80 MB | Clear "upload too large" message |
| ffmpeg missing or fails | Clear install hint on the form |
| No TTS engine | Video still produced with music + captions; note explains |

## AI usage, models, libraries & services
- **Script generation: clear template logic, no external AI API, fully offline** (the brief allows
  "an AI model or clear template logic"). Chosen because it is deterministic, free, needs no API key and
  cannot hallucinate prices, sizes or amenities.
  - *What it uses:* only the form fields. Captions are the input text verbatim; narration adds only
    fixed connector phrases.
  - *How output is checked:* `fact_check()` confirms every number and content word in the script comes
    from the input; unit tests enforce this.
- **Narration (offline, no install):** uses the computer's built-in voice — Windows (System.Speech via
  PowerShell), macOS (`say`), Linux (`espeak-ng`, install with `sudo apt install espeak-ng`), or `pyttsx3`
  if installed. Text is made speakable first ("₹1.25 Crore" → "1.25 Crore rupees", "BHK" → "B H K").
  If no voice is available the video still renders with music + captions and a note says so.
- **Libraries:** Pillow (images, text, frames), NumPy (audio synthesis/mixing), ffmpeg (encoding),
  imageio-ffmpeg (bundled ffmpeg), Python standard library (web server, form handling). Optional: pyttsx3.
- **Data:** sample photos are synthetic illustrations generated by `sample_data/make_sample_images.py`;
  contact details are fictitious.

## Tests
```bash
python -m unittest discover tests -v     # 14 tests: validation, fact-checking, scene plan, end-to-end MP4, web form
```

## Project layout
```
app.py                  web form — the app (stdlib http.server)
propvid/listing.py      data model + validation (errors vs warnings)
propvid/script.py       scene plan, captions, narration, fact check
propvid/audio.py        synthesised music, offline TTS, ducking/mixing
propvid/render.py       Ken Burns, overlays, transitions, ffmpeg encoding
propvid/pipeline.py     end-to-end orchestration
sample_data/            listing.json (demo data), listing_incomplete.json, images/
tests/                  unit + end-to-end tests
```

## Limitations / next steps
- Template narration is factual but plain; an LLM rewrite (fact-checked against the input) could improve flow.
- Offline TTS voices sound robotic; a cloud TTS (e.g. Google/ElevenLabs) would be the production choice.
- Rendering is CPU-bound (~15–20 s for a 26 s video); a job queue would be needed for many users.
- No automatic photo ranking — upload order defines scenes. Next: score photos (sharpness/brightness,
  room-type classifier) to pick the best hero shot and match photos to features.
- Next: agency logo watermark, subtitles file (.srt), multi-language scripts (Hindi), batch mode from CSV.