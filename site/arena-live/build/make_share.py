#!/usr/bin/env python3
"""Render site/arena-live/share.png (1200x630) from a real Arena Live frame.

  ffmpeg -ss 20 -i ~/Downloads/ArenaLive_Vendors/1_Rotorwash_Helicopter_ENORMOUS_vs_Jev_OpenJev_Laya.mp4 \
         -frames:v 1 frame.png
  python3 make_share.py frame.png          # needs Pillow; macOS system fonts

Numbers are read from ../data.json.
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
W, H = 1200, 630
BG = (7, 11, 18)
TEAL = (25, 195, 176)
WHITE = (244, 247, 251)
MUTED = (150, 163, 184)

AV = "/System/Library/Fonts/Avenir Next.ttc"


def font(size, idx):
    return ImageFont.truetype(AV, size, index=idx)


BOLD, DEMI, MED, REG, HEAVY = 0, 2, 5, 7, 8


def main(frame_path):
    data = json.load(open(os.path.join(SITE, "data.json")))
    vend = data["vendors"]["models"]
    e = next(m for m in vend if m["name"] == "Nagi-ENORMOUS")

    img = Image.new("RGB", (W, H), BG)

    # soft teal glow behind the phone
    glow = Image.new("RGB", (W, H), BG)
    gd = ImageDraw.Draw(glow)
    gd.ellipse((720, 40, 1180, 620), fill=(12, 70, 72))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    img = Image.blend(img, glow, 0.9)

    # phone: crop the game area of the real frame
    fr = Image.open(frame_path).convert("RGB")
    fw, fh = fr.size
    crop = fr.crop((0, int(fh * 0.03), fw, int(fh * 0.70)))
    ph = 560
    pw = round(crop.width * ph / crop.height)
    crop = crop.resize((pw, ph), Image.LANCZOS)
    px, py = W - pw - 56, (H - ph) // 2
    mask = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, pw - 1, ph - 1), 28, fill=255)
    img.paste(crop, (px, py), mask)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((px - 2, py - 2, px + pw + 1, py + ph + 1), 30, outline=(46, 60, 82), width=3)

    x = 64
    d.text((x, 58), "ARENA LIVE  ·  25 SEP 2026", font=font(19, DEMI), fill=TEAL)
    y = 96
    for line, col in (("Four AIs.", WHITE), ("Three real-time games.", WHITE),
                      ("One forward pass", MUTED), ("per decision.", MUTED)):
        d.text((x, y), line, font=font(52, BOLD), fill=col)
        y += 62

    y += 30
    big = font(64, HEAVY)
    lab = font(19, MED)
    d.text((x, y), f"{e['points']}/{data['scoring']['max_points']}", font=big, fill=TEAL)
    w1 = d.textlength(f"{e['points']}/{data['scoring']['max_points']}", font=big)
    d.text((x, y + 80), "Nagi-ENORMOUS points", font=lab, fill=MUTED)
    x2 = x + w1 + 44
    d.text((x2, y), f"{e['wins']}/{data['scoring']['max_wins']}", font=big, fill=WHITE)
    d.text((x2, y + 80), "round wins", font=lab, fill=MUTED)

    y += 124
    # roster chips
    cx = x
    f = font(18, DEMI)
    for m in vend:
        d.ellipse((cx, y + 7, cx + 12, y + 19), fill=m["color"])
        d.text((cx + 20, y), m["name"], font=f, fill=WHITE if m is e else MUTED)
        cx += 20 + d.textlength(m["name"], font=f) + 26

    d.text((x, H - 50), "nagisanzenin.github.io/nagi/arena-live", font=font(17, MED), fill=(110, 124, 146))

    out = os.path.join(SITE, "share.png")
    img.save(out, optimize=True)
    print("wrote", out, os.path.getsize(out), "bytes; phone", pw, "x", ph, "text right edge budget", px - 40)


if __name__ == "__main__":
    main(sys.argv[1])
