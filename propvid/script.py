"""Script + caption generation.

Template logic (offline, deterministic): every word comes from the input fields or
from fixed connective phrases ("Introducing", "Next:", "Available at"), so the script
cannot invent facts. `fact_check()` verifies this and is covered by unit tests.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from .listing import Listing, MAX_FEATURES


@dataclass
class Scene:
    kind: str                 # title | feature | gallery | price | cta
    image: Optional[str]      # path (None only for cta if no images left — we always reuse)
    caption: str              # big on-screen text
    sub: str = ""             # small on-screen text
    narration: str = ""       # voice-over line for this scene
    zoom_in: bool = True      # Ken Burns direction


@dataclass
class Script:
    scenes: List[Scene]
    source: str = "template"
    notes: List[str] = field(default_factory=list)

    @property
    def voiceover(self) -> str:
        return " ".join(s.narration for s in self.scenes if s.narration)

    def to_dict(self) -> dict:
        return {"source": self.source, "notes": self.notes, "voiceover": self.voiceover,
                "scenes": [s.__dict__ for s in self.scenes]}


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def build_template_script(listing: Listing, images: List[str]) -> Script:
    """Deterministic scene plan: title → 3–5 feature scenes → price → CTA."""
    if not images:
        raise ValueError("build_template_script needs at least one image")
    img_iter = _ImageCycler(images)
    scenes: List[Scene] = []

    # 1. Title
    sub_parts = [p for p in (listing.property_type, listing.location) if p]
    if listing.property_type and listing.location:
        line = f"Introducing {listing.name}, {_article(listing.property_type)} {listing.property_type} in {listing.location}."
    elif listing.location:
        line = f"Introducing {listing.name}, in {listing.location}."
    elif listing.property_type:
        line = f"Introducing {listing.name}, {_article(listing.property_type)} {listing.property_type}."
    else:
        line = f"Introducing {listing.name}."
    scenes.append(Scene("title", img_iter.next(), listing.name, "  •  ".join(sub_parts), line))

    # 2. Features (one per scene, max 5). If no features, show up to 3 gallery shots.
    feats = listing.features[:MAX_FEATURES]
    if feats:
        # Openers work with any noun phrase, so no articles/facts need to be guessed.
        openers = ["First up: {f}.", "Next: {f}.", "Then: {f}.", "You'll also love: {f}.", "And finally: {f}."]
        if len(feats) == 1:
            openers = ["Highlight: {f}."]
        for i, f in enumerate(feats):
            scenes.append(Scene("feature", img_iter.next(), f, "", openers[i].format(f=_lower_first(f)),
                                zoom_in=(i % 2 == 1)))
    else:
        for i in range(min(3, max(1, len(images) - 1))):
            scenes.append(Scene("gallery", img_iter.next(), listing.name,
                                listing.location, "", zoom_in=(i % 2 == 1)))

    # 3. Price
    if listing.price:
        scenes.append(Scene("price", img_iter.next(), listing.price, "Price",
                            f"Available at {listing.price}."))

    # 4. CTA
    cta = listing.cta or "Enquire today"
    narr = cta.rstrip(".!") + "."
    if listing.contact:
        spoken = re.sub(r"\s*[|/,;]\s*", " or ", listing.contact)  # "a | b" reads aloud as "a or b"
        narr += f" Contact {spoken}."
    scenes.append(Scene("cta", images[0], cta, listing.contact, narr, zoom_in=False))
    return Script(scenes=scenes)


class _ImageCycler:
    """Uses each image once before repeating (repeats get a different zoom direction)."""
    def __init__(self, images: List[str]):
        self.images, self.i = images, 0

    def next(self) -> str:
        img = self.images[self.i % len(self.images)]
        self.i += 1
        return img


def _lower_first(text: str) -> str:
    # keep acronyms/proper nouns like "3 BHK" or "Gym" sensible: only lowercase if 2nd char is lowercase
    if len(text) > 1 and text[0].isupper() and text[1].islower():
        return text[0].lower() + text[1:]
    return text


# ---------------------------------------------------------------- fact checking
_NUM_RE = re.compile(r"\d[\d,\.]*")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-']+")
# Connective words the template may add; anything else must come from the input.
_ALLOWED_WORDS = set("""
a an the and or but with of in at on for to from by is are it its it's this that these those your you
our we us first up next then love also finally highlight you'll featuring features feature enjoy offers offering boasts boasting discover introducing meet
welcome home here there plus also includes including include comes complete equipped space spaces
available priced price at just only now today call contact enquire enquiry reach out book visit
schedule viewing tour more details information learn about don't miss chance yours make step inside
step into right perfect ideal everything need life living style comfort convenient convenience
beautiful stunning modern spacious bright elegant designed well located location situated nestled
""".split())


def fact_check(candidate: str, listing: Listing) -> List[str]:
    """Return a list of problems; empty list means the line only uses supplied facts."""
    source = " ".join([listing.name, listing.location, listing.price, listing.property_type,
                       listing.cta, listing.contact, *listing.features]).lower()
    src_nums = {n.strip(".,") for n in _NUM_RE.findall(source)}
    src_words = set(_WORD_RE.findall(source))
    problems = []
    for n in _NUM_RE.findall(candidate.lower()):
        if n.strip(".,") not in src_nums:
            problems.append(f"number '{n}' not in input")
    for w in _WORD_RE.findall(candidate.lower()):
        if w not in src_words and w not in _ALLOWED_WORDS and w.rstrip("s") not in src_words:
            problems.append(f"word '{w}' not in input")
    return problems