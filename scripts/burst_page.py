#!/usr/bin/env python3
"""Burst landing page helper (site/burst/). Not published: lives outside site/.

  python3 scripts/burst_page.py check              # list unresolved {{PLACEHOLDERS}} under site/; exit 1 if any
  python3 scripts/burst_page.py fill values.json   # replace {{NAME}} in site/burst/* from {"NAME": "value", ...}
  python3 scripts/burst_page.py preview [out.html] # self-contained single-file preview (default preview/burst.html)

`fill` refuses unknown keys and never writes a value that itself contains "{{". Every value must come from a receipt
listed in docs/burst/PUBLISH_CHECKLIST.md. The Pages workflow runs `check` before deploying.
"""
import base64, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
BURST = os.path.join(SITE, "burst")
PH = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
TEXT_EXT = (".html", ".js", ".json", ".css", ".svg", ".txt", ".xml")
PUBLIC = "https://nagisanzenin.github.io/nagi/"


def site_files():
    for d, _, files in os.walk(SITE):
        for f in files:
            if f.endswith(TEXT_EXT):
                yield os.path.join(d, f)


def check():
    found = {}
    for path in site_files():
        text = open(path, encoding="utf-8").read()
        for m in PH.finditer(text):
            found.setdefault(m.group(1), set()).add(os.path.relpath(path, ROOT))
    for name in sorted(found):
        print(f"{name:28s} {', '.join(sorted(found[name]))}")
    print(f"{len(found)} unresolved placeholder(s)" if found else "OK: no placeholders left under site/")
    return 1 if found else 0


def fill(values_path):
    values = json.load(open(values_path, encoding="utf-8"))
    bad = [k for k, v in values.items() if not re.fullmatch(r"[A-Z0-9_]+", k) or "{{" in str(v)]
    if bad:
        sys.exit(f"refused: invalid keys or values containing '{{{{': {bad}")
    known = set()
    for path in site_files():
        known |= set(PH.findall(open(path, encoding="utf-8").read()))
    unknown = sorted(set(values) - known)
    if unknown:
        sys.exit(f"refused: keys not present on the site: {unknown}")
    for path in site_files():
        text = open(path, encoding="utf-8").read()
        new = PH.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text)
        if new != text:
            open(path, "w", encoding="utf-8").write(new)
            print("filled:", os.path.relpath(path, ROOT))
    return check()


def data_uri(path, mime):
    return f"data:{mime};base64," + base64.b64encode(open(path, "rb").read()).decode()


def preview(out):
    html = open(os.path.join(BURST, "index.html"), encoding="utf-8").read()
    css = open(os.path.join(SITE, "assets", "nagi.css"), encoding="utf-8").read()
    js = open(os.path.join(BURST, "burst.js"), encoding="utf-8").read()
    data = open(os.path.join(BURST, "data.json"), encoding="utf-8").read()
    html = html.replace('<link rel="stylesheet" href="../assets/nagi.css">', f"<style>{css}</style>")
    html = html.replace('<link rel="preload" href="data.json" as="fetch" crossorigin>', "")
    html = re.sub(r'<link rel="icon"[^>]*>', "", html)
    html = html.replace('<script src="burst.js" defer></script>',
                        '<script type="application/json" id="burst-data">' + data.replace("</", "<\\/") + "</script>"
                        + f"<script>{js}</script>")
    html = html.replace('src="../assets/wordmark.svg"', f'src="{data_uri(os.path.join(SITE, "assets", "wordmark.svg"), "image/svg+xml")}"')
    html = html.replace('src="../assets/mascot-128.png"', f'src="{data_uri(os.path.join(SITE, "assets", "mascot-128.png"), "image/png")}"')
    # clips are not published yet: show a labelled empty frame instead of requesting missing media
    html = re.sub(r'<video\b.*?</video>', '<span>Clip pending<br>(Burst-labelled render)</span>', html, flags=re.S)
    # site-relative links -> the public site, so the preview's links work from anywhere
    html = re.sub(r'href="\.\./([^"]*)"', lambda m: f'href="{PUBLIC}{m.group(1)}"', html)
    html = html.replace('href="data.json"', f'href="{PUBLIC}burst/data.json"')
    html = html.replace("<body>", '<body><div style="background:#FF4D94;color:#111114;font:700 12px/1.4 \'IBM Plex Mono\',monospace;'
                        'padding:6px 12px;text-align:center">PRIVATE PREVIEW · DRAFT · pink {{…}} fields are pending numbers</div>', 1)
    # make pending text visible (text nodes only; attributes, <script> and <style> untouched)
    parts, skip = re.split(r"(<[^>]+>)", html), False
    for i, part in enumerate(parts):
        if part.startswith("<"):
            low = part.lower()
            skip = low.startswith(("<script", "<style")) or (skip and not low.startswith(("</script", "</style")))
        elif not skip:
            parts[i] = PH.sub(lambda m: f'<span class="ph">{m.group(0)}</span>', part)
    html = "".join(parts)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write(html)
    print("preview:", out, f"{len(html) / 1024:.0f} KiB")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        sys.exit(check())
    if cmd == "fill" and len(sys.argv) == 3:
        sys.exit(fill(sys.argv[2]))
    if cmd == "preview":
        sys.exit(preview(sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "preview", "burst.html")))
    sys.exit(__doc__)
