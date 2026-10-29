#!/usr/bin/env python3
"""Creates synthetic (non-real, copyright-free) property illustrations for testing.

Run:  python sample_data/make_sample_images.py
Swap these for real listing photos in practice.
"""
import os
import random

from PIL import Image, ImageDraw, ImageFilter

W, H = 1600, 1000
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")
random.seed(7)


def grad(top, bottom, w=W, h=H):
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    return im


def finish(im, name):
    im = im.filter(ImageFilter.GaussianBlur(1.2))
    noise = Image.effect_noise((W, H), 12).convert("RGB")
    im = Image.blend(im, noise, 0.04)
    os.makedirs(OUT, exist_ok=True)
    im.save(os.path.join(OUT, name), quality=90)


def room(wall, floor):
    im = grad(wall, tuple(max(0, c - 30) for c in wall))
    d = ImageDraw.Draw(im)
    d.polygon([(0, 700), (W, 700), (W, H), (0, H)], fill=floor)
    for x in range(-400, W + 400, 160):  # floor planks perspective
        d.line([(W / 2 + (x - W / 2) * 0.55, 700), (x, H)], fill=tuple(c - 18 for c in floor), width=3)
    return im, d


def window(d, x, y, w, h, sky=((140, 190, 235), (225, 238, 250))):
    sky_im = grad(sky[0], sky[1], w, h)
    return sky_im, (x, y)


def living():
    im, d = room((236, 228, 214), (176, 132, 92))
    s, pos = window(d, 980, 140, 460, 470)
    im.paste(s, pos)
    d.rectangle([980, 140, 1440, 610], outline=(250, 250, 250), width=14)
    d.line([(1210, 140), (1210, 610)], fill=(250, 250, 250), width=10)
    d.rectangle([160, 520, 820, 700], fill=(70, 92, 120))      # sofa
    d.rectangle([140, 470, 840, 560], fill=(84, 108, 138))
    for cx in (300, 480, 660):
        d.rounded_rectangle([cx - 70, 480, cx + 70, 600], 20, fill=(222, 196, 140))
    d.ellipse([360, 760, 760, 840], fill=(60, 50, 44))         # coffee table
    d.rectangle([60, 160, 360, 380], fill=(190, 120, 80))      # art
    d.rectangle([80, 180, 340, 360], fill=(230, 170, 110))
    d.line([(1520, 300), (1520, 700)], fill=(40, 40, 40), width=6)  # lamp
    d.ellipse([1470, 240, 1570, 320], fill=(250, 230, 170))
    finish(im, "02_living_room.jpg")


def kitchen():
    im, d = room((240, 240, 236), (205, 205, 200))
    d.rectangle([0, 520, W, 720], fill=(60, 72, 88))           # lower cabinets
    d.rectangle([0, 500, W, 530], fill=(235, 232, 225))        # counter
    for x in range(0, W, 200):
        d.rectangle([x + 8, 548, x + 192, 708], outline=(80, 94, 112), width=4)
        d.rectangle([x + 90, 600, x + 110, 606], fill=(200, 200, 200))
    d.rectangle([0, 120, W, 340], fill=(66, 78, 94))           # upper cabinets
    for x in range(0, W, 200):
        d.rectangle([x + 8, 128, x + 192, 332], outline=(86, 100, 118), width=4)
    d.rectangle([0, 340, W, 500], fill=(222, 228, 232))        # backsplash
    for x in range(0, W, 60):
        d.line([(x, 340), (x, 500)], fill=(205, 212, 218), width=2)
    d.rectangle([520, 830, 1080, 900], fill=(240, 236, 228))   # island
    d.rectangle([540, 900, 1060, H], fill=(70, 82, 98))
    for x in (640, 960):
        d.line([(x, 0), (x, 200)], fill=(30, 30, 30), width=3)
        d.ellipse([x - 40, 190, x + 40, 240], fill=(245, 205, 120))
    finish(im, "03_kitchen.jpg")


def bedroom():
    im, d = room((214, 222, 230), (160, 122, 90))
    s, pos = window(d, 120, 160, 380, 420, ((250, 190, 140), (250, 225, 190)))
    im.paste(s, pos)
    d.rectangle([120, 160, 500, 580], outline=(245, 245, 245), width=12)
    d.rectangle([700, 380, 1400, 520], fill=(120, 92, 70))     # headboard
    d.rectangle([660, 560, 1440, 820], fill=(245, 245, 242))   # bed
    d.rectangle([660, 690, 1440, 820], fill=(150, 170, 190))
    for x in (760, 1100):
        d.rounded_rectangle([x, 520, x + 240, 610], 26, fill=(250, 250, 250))
    d.rectangle([1470, 600, 1580, 720], fill=(110, 84, 64))
    d.ellipse([1490, 520, 1560, 600], fill=(250, 228, 170))
    finish(im, "04_bedroom.jpg")


def balcony():
    im = grad((90, 150, 220), (250, 200, 160))
    d = ImageDraw.Draw(im)
    for i in range(14):  # skyline
        x = i * 120 + random.randint(-20, 20)
        h = random.randint(180, 420)
        d.rectangle([x, 680 - h, x + 100, 700], fill=(70 + i * 3, 86 + i * 2, 120))
        for wy in range(700 - h + 20, 690, 36):
            for wx in range(x + 12, x + 90, 26):
                if random.random() < 0.5:
                    d.rectangle([wx, wy, wx + 12, wy + 18], fill=(250, 220, 150))
    d.rectangle([0, 700, W, H], fill=(150, 140, 130))          # balcony floor
    d.rectangle([0, 600, W, 615], fill=(60, 60, 60))           # railing
    for x in range(0, W, 70):
        d.line([(x, 615), (x, 760)], fill=(60, 60, 60), width=5)
    d.rectangle([1100, 760, 1400, 790], fill=(120, 80, 50))    # seating
    for x in (1080, 1360):
        d.rectangle([x, 790, x + 60, 900], fill=(110, 75, 48))
    d.ellipse([140, 700, 300, 900], fill=(60, 130, 70))        # plant
    d.rectangle([180, 860, 260, 960], fill=(170, 100, 70))
    finish(im, "05_balcony_view.jpg")


def exterior():
    im = grad((40, 60, 110), (240, 150, 110))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 860, W, H], fill=(60, 90, 60))
    for bx, bw, top in ((300, 360, 120), (760, 420, 60), (1240, 300, 220)):
        d.rectangle([bx, top, bx + bw, 870], fill=(210, 205, 200))
        for y in range(top + 30, 850, 52):
            d.rectangle([bx, y + 34, bx + bw, y + 40], fill=(180, 175, 170))  # balcony slabs
            for x in range(bx + 18, bx + bw - 30, 52):
                lit = random.random() < 0.55
                d.rectangle([x, y, x + 32, y + 30], fill=(255, 214, 140) if lit else (70, 90, 120))
    for x in range(40, W, 180):  # trees
        d.ellipse([x, 760, x + 120, 880], fill=(40, 100, 55))
    finish(im, "01_exterior.jpg")


def amenity():
    im = grad((120, 180, 235), (220, 236, 248))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 520, W, H], fill=(225, 215, 195))          # deck
    d.polygon([(260, 620), (1340, 620), (1520, 940), (80, 940)], fill=(40, 160, 200))  # pool
    for i in range(10):
        y = 650 + i * 30
        d.line([(200 + i * 10, y), (1400 - i * 10, y)], fill=(120, 210, 235), width=3)
    for x in (120, 1380):
        d.rectangle([x, 300, x + 40, 560], fill=(120, 90, 60))
        d.ellipse([x - 120, 200, x + 160, 340], fill=(50, 140, 70))
    for x in (300, 560, 1000, 1260):  # loungers
        d.polygon([(x, 560), (x + 160, 560), (x + 180, 600), (x - 20, 600)], fill=(250, 250, 250))
    finish(im, "06_pool_amenity.jpg")


if __name__ == "__main__":
    for fn in (exterior, living, kitchen, bedroom, balcony, amenity):
        fn()
    print(f"Wrote sample images to {OUT}")