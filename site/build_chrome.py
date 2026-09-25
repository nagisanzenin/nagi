#!/usr/bin/env python3
"""Stamp the shared Nagi chrome (head links, header, footer) into every page under site/.

  python3 site/build_chrome.py

Idempotent: blocks live between <!--nx:head-->, <!--nx:header-->, <!--nx:footer--> markers and are
rewritten on every run. On the first run a page's own <header>/<footer> is replaced (replay pages
keep their footer content as a page note). Styling: site/assets/nagi.css (brand v3, docs/brand).
"""
import os, re

SITE = os.path.dirname(os.path.abspath(__file__))
HF = "https://huggingface.co/nagisanzeninz"
GH = "https://github.com/nagisanzenin/nagi"

# path, depth prefix, active nav key, page kind, optional on-page anchors
PAGES = [
    ("index.html", "", "bench", "home", [("Results", "#results"), ("Nagi tiers", "#tiers"), ("Method", "#method"), ("Reproduce", "#evidence")]),
    ("arena-live/index.html", "../", "live", "live", [("Results", "#results"), ("Games", "#rotorwash"), ("Nagi lines", "#family"), ("Lab notes", "#lab"), ("Fairness", "#fair")]),
    ("arena/index.html", "../", "replays", "hub", []),
    ("bomber-huge/index.html", "../", "replays", "legacy", []),
    ("bomber-realtime/index.html", "../", "replays", "legacy", []),
    ("bomber/index.html", "../", "replays", "legacy", []),
    ("snake/index.html", "../", "replays", "legacy", []),
]

NAV = [("bench", "Benchmark", ""), ("live", "Arena Live", "arena-live/"), ("replays", "Replays", "arena/")]


def head(p):
    return (f'<!--nx:head--><link rel="icon" href="{p}assets/favicon.svg" type="image/svg+xml">'
            '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Anton&family=IBM+Plex+Mono:wght@500;600;700&family=Inter:wght@400;500;600;700;800&display=swap">'
            f'<link rel="stylesheet" href="{p}assets/nagi.css"><!--/nx:head-->')


def header(p, active, sub):
    nav = "".join(f'<a href="{p}{href}"' + (' aria-current="page"' if key == active else '') + f'>{label}</a>' for key, label, href in NAV)
    nav += f'<a href="{HF}">Models ↗</a><a href="{GH}">GitHub ↗</a>'
    subnav = ""
    if sub:
        subnav = '<nav class="nx-sub" aria-label="On this page"><b>On this page</b>' + "".join(f'<a href="{h}">{l}</a>' for l, h in sub) + '</nav>'
    return (f'<!--nx:header--><header class="nx-bar"><div class="nx-in"><div class="nx-row">'
            f'<a class="nx-mark" href="{p}" aria-label="Nagi home"><img src="{p}assets/wordmark.svg" alt="nagi" width="61" height="30"><span>System One</span></a>'
            f'<nav class="nx-nav" aria-label="Site">{nav}</nav></div>{subnav}</div></header><!--/nx:header-->')


def footer(p, active, page):
    def link(href, label, cur=False):
        return f'<li><a href="{href}"' + (' aria-current="page"' if cur else '') + f'>{label}</a></li>'
    ext = lambda h, l: f'<li><a href="{h}">{l} ↗</a></li>'
    extra = '<span id="version"></span> · ' if page == "home" else ""
    return ('<!--nx:footer--><footer class="nx-foot"><div class="nx-in">'
            f'<div class="nx-brand"><img class="m" src="{p}assets/mascot-128.png" alt="Nagi mascot" width="72" height="72">'
            f'<div><img class="w" src="{p}assets/wordmark.svg" alt="nagi" width="61" height="30"><p>Typed decisions.<br>Visible probabilities.</p></div></div>'
            '<div class="nx-cols">'
            '<div><h4>Benchmarks</h4><ul>' + link(f"{p}arena-live/", "Arena Live", active == "live") + link(p or "./", "Public decision benchmark", active == "bench") + '</ul></div>'
            '<div><h4>Replays</h4><ul>' + link(f"{p}arena/", "All replays", page == "hub") + link(f"{p}bomber-huge/", "Real-time Bomber · HUGE")
            + link(f"{p}bomber-realtime/", "Real-time Bomber · BIG") + link(f"{p}bomber/", "Turn-based Bomber") + link(f"{p}snake/", "Snake pilot") + '</ul></div>'
            '<div><h4>Models</h4><ul>' + ext(f"{HF}/Nagi-ENORMOUS", "Nagi-ENORMOUS 27B") + ext(f"{HF}/Nagi-HUGE", "Nagi-HUGE 12B")
            + ext(f"{HF}/nagi-big-v3", "Nagi-BIG 4B") + ext(f"{HF}/nagi-smol-v0", "Nagi-SMOL 0.5B") + '</ul></div>'
            '<div><h4>Code</h4><ul>' + ext(GH, "Nagi SDK on GitHub") + ext(f"{GH}/tree/main/bench", "Benchmark data") + ext(f"{GH}/tree/main/docs/brand", "Brand kit")
            + ext(f"{GH}/issues", "Questions or corrections") + '</ul></div></div>'
            f'<p class="nx-legal">{extra}Self-hosted System One models. Probabilities are model outputs, not guarantees.</p>'
            '</div></footer><!--/nx:footer-->')


def sub_block(html, name, new, fallback):
    pat = re.compile(rf'<!--nx:{name}-->.*?<!--/nx:{name}-->', re.S)
    if pat.search(html):
        return pat.sub(lambda m: new, html, count=1)
    return fallback(html)


def main():
    for rel, p, active, kind, sub in PAGES:
        path = os.path.join(SITE, rel)
        html = open(path).read()
        html = re.sub(r'<link rel="icon"[^>]*>', '', html) if '<!--nx:head-->' not in html else html
        html = sub_block(html, "head", head(p), lambda h: h.replace("</head>", head(p) + "</head>", 1))

        def first_header(h):
            m = re.search(r'<header\b[\s\S]*?</header>', h)
            return h[:m.start()] + header(p, active, sub) + h[m.end():]
        html = sub_block(html, "header", header(p, active, sub), first_header)

        def first_footer(h):
            m = re.search(r'<footer\b[\s\S]*?</footer>', h)
            if kind == "legacy":
                note = re.sub(r'^<footer\b[^>]*>', '<div class="page-foot">', m.group(0))[:-len('</footer>')] + '</div>'
                h = h[:m.start()] + note + h[m.end():]
                return h.replace("</body>", footer(p, active, kind) + "</body>", 1)
            return h[:m.start()] + footer(p, active, kind) + h[m.end():]
        html = sub_block(html, "footer", footer(p, active, kind), first_footer)

        if kind == "legacy" and 'class="nx-legacy"' not in html:
            html = html.replace("<body>", '<body class="nx-legacy">', 1)
            if "<main" not in html:  # snake: wrap page content
                html = html.replace("<!--/nx:header-->", '<!--/nx:header--><div class="nx-page">', 1)
                html = html.replace("<!--nx:footer-->", '</div><!--nx:footer-->', 1)
        open(path, "w").write(html)
        print("chrome:", rel)


if __name__ == "__main__":
    main()
