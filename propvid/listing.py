"""Listing data model + validation.

Validation never raises on bad user input; it returns a list of errors (fatal)
and warnings (the video is still produced) so the web form can show a
useful message instead of a stack trace.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import List, Tuple

from PIL import Image, UnidentifiedImageError

MIN_IMAGES = 4
MAX_IMAGES = 8
MAX_FEATURES = 5
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class ListingError(Exception):
    """Raised when input cannot produce a video. Message is user-facing."""


@dataclass
class Listing:
    name: str = ""
    location: str = ""
    price: str = ""
    property_type: str = ""
    features: List[str] = field(default_factory=list)
    cta: str = ""
    contact: str = ""
    images: List[str] = field(default_factory=list)

    # ---------- construction ----------
    @classmethod
    def from_dict(cls, data: dict, base_dir: str = ".") -> "Listing":
        def s(key: str) -> str:
            v = data.get(key, "")
            return str(v).strip() if v is not None else ""

        feats = data.get("features") or []
        if isinstance(feats, str):  # allow "a; b; c" or newline separated
            feats = [f for part in feats.replace("\n", ";").split(";") for f in [part.strip()] if f]
        feats = [str(f).strip() for f in feats if str(f).strip()]

        imgs = data.get("images") or []
        if isinstance(imgs, str):
            imgs = [imgs]
        imgs = [p if os.path.isabs(p) else os.path.normpath(os.path.join(base_dir, p)) for p in imgs]

        return cls(
            name=s("name"), location=s("location"), price=s("price"),
            property_type=s("property_type") or s("type"), features=feats,
            cta=s("cta"), contact=s("contact"), images=imgs,
        )

    @classmethod
    def from_json_file(cls, path: str) -> "Listing":
        if not os.path.isfile(path):
            raise ListingError(f"Input file not found: {path}")
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ListingError(f"Input file is not valid JSON ({path}): line {exc.lineno}, {exc.msg}")
        if not isinstance(data, dict):
            raise ListingError("Input JSON must be an object with fields like name, price, images.")
        return cls.from_dict(data, base_dir=os.path.dirname(os.path.abspath(path)))

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in
                ("name", "location", "price", "property_type", "features", "cta", "contact", "images")}

    # ---------- validation ----------
    def validate(self) -> Tuple[List[str], List[str], List[str]]:
        """Return (errors, warnings, usable_image_paths)."""
        errors: List[str] = []
        warnings: List[str] = []

        if not self.name:
            errors.append("Property name is required (it is the video's title).")
        for label, value in (("location", self.location), ("price", self.price),
                             ("property type", self.property_type)):
            if not value:
                warnings.append(f"No {label} supplied — it will be left out of the video.")
        if not self.features:
            warnings.append("No key features supplied — photo scenes will be shown without feature captions.")
        elif len(self.features) > MAX_FEATURES:
            warnings.append(f"{len(self.features)} features supplied; only the first {MAX_FEATURES} are used to keep the video short.")
        if not self.cta and not self.contact:
            warnings.append("No CTA/contact supplied — a generic 'Enquire today' end card is used.")

        usable: List[str] = []
        for p in self.images:
            ok, why = check_image(p)
            if ok:
                usable.append(p)
            else:
                warnings.append(f"Skipped image {os.path.basename(p) or p}: {why}")

        if not usable:
            errors.append("No usable images. Provide 4–8 JPG/PNG/WebP property photos.")
        elif len(usable) < MIN_IMAGES:
            warnings.append(f"Only {len(usable)} usable image(s); {MIN_IMAGES}–{MAX_IMAGES} recommended. Images will be reused with different framing.")
        if len(usable) > MAX_IMAGES:
            warnings.append(f"{len(usable)} images supplied; only the first {MAX_IMAGES} are used.")
            usable = usable[:MAX_IMAGES]
        return errors, warnings, usable


def check_image(path: str) -> Tuple[bool, str]:
    if not path:
        return False, "empty path"
    if not os.path.isfile(path):
        return False, "file not found"
    if os.path.splitext(path)[1].lower() not in IMAGE_EXTS:
        return False, "unsupported file type (use JPG, PNG, WebP or BMP)"
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            w, h = im.size
    except (UnidentifiedImageError, OSError) as exc:
        return False, f"cannot be read as an image ({exc.__class__.__name__})"
    if w < 320 or h < 240:
        return False, f"too small ({w}x{h}); minimum 320x240"
    return True, ""