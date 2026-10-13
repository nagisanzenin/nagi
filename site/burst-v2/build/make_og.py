#!/usr/bin/env python3
"""Build and check the social card site/burst-v2/og.png (1200x630) for the Nagi Burst V2 page.

  python3 site/burst-v2/build/make_og.py                 # write site/burst-v2/og.png
  python3 site/burst-v2/build/make_og.py check           # rebuild in a temp dir; exit 1 unless sha256 == og.png
  python3 site/burst-v2/build/make_og.py frame           # re-extract media/og-frame.jpg from the pinned repo clip

Inputs: site/burst-v2/media/og-frame.jpg (one frame of the raw 1x Booster Gauntlet replay in site/arena/media/: sealed
eval seed #34, the median V2-Jev margin seed, all three seats; clip, sha256 and frame are pinned in FRAME below and in
bench/burst_v2/receipts/page_media.json) and site/burst-v2/data.json. Every number on the card is read from data.json `values` (the page's receipt-stamped
strings); labels below are prose and contain no measured number.

Needs ffmpeg with drawtext (libfreetype) and the macOS system fonts in FONTS. Python stdlib only. The PNG is
byte-deterministic for a fixed ffmpeg build and fixed font files; `check` compares sha256 on that basis.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE_DIR = os.path.dirname(HERE)
DATA = os.path.join(PAGE_DIR, "data.json")
FRAME_JPG = os.path.join(PAGE_DIR, "media", "og-frame.jpg")
OUT = os.path.join(PAGE_DIR, "og.png")
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"

W, H = 1200, 630
IMG_W = 440                      # right-hand game panel, full height
IMG_X = W - IMG_W
ROOT = os.path.dirname(os.path.dirname(PAGE_DIR))
FRAME = {                        # og-frame.jpg provenance (raw 1x 3-seat replay, 1080x1920, 30 fps)
    "src": "site/arena/media/v2-BoosterGauntlet-V2-V1-Jev-seed34.mp4",
    "src_sha256": "ded887ad4e927a33ce95e3f783f30b001a67503fec1a16314b9155a66a1d35b4",
    "frame": 300,                # 10.0 s; on-screen game clock 10.0 s
    "crop": "662:948:209:381",   # w:h:x:y in the source: sky, three rockets, ship and sea; HUD excluded
}

INK, BONE, YELLOW, GREEN = "0x111114", "0xF3EEDB", "0xF5E642", "0x36D988"
MUTED, LINE = "0xB7B4AC", "0x48484D"
SUP = "/System/Library/Fonts/Supplemental/"
FONTS = {
    "display": SUP + "Impact.ttf",            # first face in the site's --nagi-display stack
    "bold": SUP + "Arial Bold.ttf",
    "reg": SUP + "Arial.ttf",
    "mono": "/System/Library/Fonts/Menlo.ttc",
}

# (label, value template over data.json values, sub-label template); {k} = values[k]
STATS = [
    ("UNSEEN MACHINES", "{g_theta}", "success · {g_families} unseen families"),
    ("ARENA VS NAGI BURST V1", "{a_snake_W} · {a_rotorwash_W} · {a_booster_W}",
     "win share · Snake · Rotorwash · Booster"),
    ("LEARNED CORE", "{core_params}", "parameters · numpy only"),
    ("DECISION LATENCY", "≤ {l_max_ucb}", "largest p95 upper bound, one CPU thread"),
]
KEYS = ["g_theta", "g_families", "a_snake_W", "a_rotorwash_W", "a_booster_W", "core_params", "l_max_ucb",
        "sdk_tag"]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def values():
    with open(DATA, encoding="utf-8") as f:
        v = json.load(f)["values"]
    missing = [k for k in KEYS if k not in v]
    if missing:
        raise SystemExit(f"data.json values missing {missing}")
    return v


def texts(v):
    """[(text, font, size, color, x, y)] — every number is a data.json value."""
    t = [
        (f"NAGI SDK {v['sdk_tag']}  ·  nagi.burst2", "bold", 17, GREEN, 56, 50),
        ("NAGI BURST V2", "display", 112, BONE, 52, 78),
        ("Write the rules.", "bold", 40, BONE, 56, 214),
        ("Get the decision.", "bold", 40, YELLOW, 56, 262),
    ]
    cols, rows = (56, 300), (356, 460)
    for i, (lab, val, sub) in enumerate(STATS):
        x, y = cols[i % 2], rows[i // 2]
        t += [(lab, "bold", 14, GREEN, x, y),
              (val.format(**v), "bold", 44, BONE, x, y + 24),
              (sub.format(**v), "reg", 15, MUTED, x, y + 76)]
    t.append(("nagisanzenin.github.io/nagi/burst-v2", "mono", 17, MUTED, 56, 588))
    return t


def esc(p):
    return p.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def build(out_png):
    for f in [FRAME_JPG, *FONTS.values()]:
        if not os.path.isfile(f):
            raise SystemExit(f"missing input {f}")
    v = values()
    tmp = tempfile.mkdtemp(prefix="bv2og_")
    try:
        chain = [f"drawbox=x={IMG_X - 4}:y=0:w=4:h={H}:color={YELLOW}:t=fill",
                 f"drawbox=x=56:y=338:w={IMG_X - 4 - 56 - 40}:h=1:color={LINE}:t=fill",
                 f"drawbox=x=56:y=572:w={IMG_X - 4 - 56 - 40}:h=1:color={LINE}:t=fill"]
        for i, (txt, font, size, color, x, y) in enumerate(texts(v)):
            tf = os.path.join(tmp, f"t{i}.txt")
            with open(tf, "w", encoding="utf-8") as f:
                f.write(txt)
            chain.append(f"drawtext=fontfile='{esc(FONTS[font])}':textfile='{esc(tf)}':expansion=none:"
                         f"fontsize={size}:fontcolor={color}:x={x}:y={y}")
        fc = (f"color=c={INK}:s={W}x{H}:r=1:d=1,format=rgb24[bg];"
              f"[0:v]format=rgb24[img];[bg][img]overlay=x={IMG_X}:y=0:format=rgb,"
              + ",".join(chain) + ",format=rgb24[o]")
        cmd = [FFMPEG, "-v", "error", "-y", "-i", FRAME_JPG, "-filter_complex", fc, "-map", "[o]",
               "-frames:v", "1", "-fflags", "+bitexact", "-flags", "+bitexact", "-c:v", "png",
               "-pred", "mixed", "-compression_level", "9", out_png]
        subprocess.run(cmd, check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def frame():
    src = os.path.join(ROOT, FRAME["src"])
    if sha256(src) != FRAME["src_sha256"]:
        raise SystemExit("frame: source sha256 != pinned FRAME['src_sha256']")
    cmd = [FFMPEG, "-v", "error", "-y", "-i", src, "-frames:v", "1", "-fps_mode", "passthrough",
           "-vf", f"select=eq(n\\,{FRAME['frame']}),crop={FRAME['crop']},scale={IMG_W}:{H}:flags=lanczos", "-q:v", "2",
           "-fflags", "+bitexact", "-flags", "+bitexact", FRAME_JPG]
    subprocess.run(cmd, check=True)
    print(json.dumps({"og-frame.jpg": sha256(FRAME_JPG), "bytes": os.path.getsize(FRAME_JPG)}))


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "build"
    if cmd == "build":
        build(OUT)
        print(json.dumps({"og.png": sha256(OUT), "bytes": os.path.getsize(OUT)}))
    elif cmd == "check":
        if not os.path.isfile(OUT):
            raise SystemExit("check: og.png missing")
        tmp = tempfile.mkdtemp(prefix="bv2og_check_")
        try:
            p = os.path.join(tmp, "og.png")
            build(p)
            new, old = sha256(p), sha256(OUT)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if new != old:
            print(f"og.png FAIL: rebuilt {new} != committed {old}")
            return 1
        print(f"og.png OK {old}")
    elif cmd == "frame":
        frame()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
