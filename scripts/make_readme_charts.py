#!/usr/bin/env python3
"""Render the README charts as SVG in the Nagi brand (docs/brand/brand-guideline.md).

  python3 scripts/make_readme_charts.py      # writes docs/charts/*.svg

Brand rules applied: ink background, bone text, square bars (radius 0), clear rules, condensed
italic uppercase display titles, mono numbers, Nagi highlighted in green WITH a label, others in
muted neutrals, one yellow tape or pink stamp per chart, no gradients/glow/texture on data.
Arena numbers are read from bench/arena_live/results_*.json; public-suite numbers are the frozen
common-evidence values reported in bench/HUGE_PUBLIC.md and docs/ENORMOUS_RELEASE.md.
"""
import json, os, statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "charts")
INK, BONE, YEL, GRN, PNK, MUT, LINE, PANEL = "#111114", "#F3EEDB", "#F5E642", "#36D988", "#FF4D94", "#B7B4AC", "#48484D", "#1C1C21"
DISPLAY = "Impact, Haettenschweiler, 'Arial Narrow Bold', 'Arial Narrow', sans-serif"
BODY = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "'IBM Plex Mono', Menlo, Consolas, monospace"
W = 960
GAMES = (("rotorwash", "Rotorwash"), ("lightcycle", "Lightcycle"), ("stack", "Stack"))
TINT = (1.0, .66, .38)  # three flat tints of the same colour, one per game


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def frame(h, title, kicker, body, mark=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {h}" width="{W}" height="{h}" role="img" aria-label="{esc(title)}">'
            f'<rect width="{W}" height="{h}" fill="{INK}"/>'
            f'<rect x="0.5" y="0.5" width="{W-1}" height="{h-1}" fill="none" stroke="{LINE}"/>'
            f'<text x="36" y="44" fill="{MUT}" font-family="{MONO}" font-size="13" font-weight="600" letter-spacing="1.8">{esc(kicker.upper())}</text>'
            f'<text x="34" y="92" fill="{BONE}" font-family="{DISPLAY}" font-size="46" font-style="italic" letter-spacing="-0.5">{esc(title.upper())}</text>'
            f'<line x1="36" x2="{W-36}" y1="112" y2="112" stroke="{BONE}" stroke-width="2"/>'
            f'{mark}{body}</svg>')


def tape(x, y, text, w=None):
    w = w or 18 + 9.2 * len(text)
    return (f'<g transform="translate({x} {y}) rotate(-3)"><rect x="4" y="4" width="{w}" height="30" fill="{PNK}"/>'
            f'<rect width="{w}" height="30" fill="{YEL}"/><text x="{w/2}" y="20" text-anchor="middle" fill="{INK}" font-family="{MONO}" '
            f'font-size="14" font-weight="700" letter-spacing="1.2">{esc(text)}</text></g>')


def stamp(x, y, text):
    w = 20 + 10 * len(text)
    return (f'<g transform="translate({x} {y}) rotate(5)"><rect width="{w}" height="32" fill="none" stroke="{PNK}" stroke-width="2.5"/>'
            f'<text x="{w/2}" y="22" text-anchor="middle" fill="{PNK}" font-family="{MONO}" font-size="15" font-weight="700" letter-spacing="2">{esc(text)}</text></g>')


def arena_chart(fn, results, roster, title, kicker):
    rows = []
    for key, name, note in roster:
        per = [results[g]["models"][key]["points"] for g, _ in GAMES]
        wins = sum(results[g]["models"][key]["wins"] for g, _ in GAMES)
        rows.append((name, note, per, sum(per), wins))
    rows.sort(key=lambda r: (-r[3], -r[4]))
    x0, x1, top, rh = 250, W - 170, 176, 70
    scale = (x1 - x0) / 90
    body = [f'<text x="{x0}" y="150" fill="{MUT}" font-family="{MONO}" font-size="12" letter-spacing="1">'
            f'BAR = POINTS OF 90 · SEGMENTS: ROTORWASH / LIGHTCYCLE / STACK (30 EACH)</text>']
    for v in (0, 30, 60, 90):
        x = x0 + v * scale
        body.append(f'<line x1="{x}" x2="{x}" y1="{top-12}" y2="{top + rh*len(rows) - 18}" stroke="{LINE}" stroke-dasharray="{"" if v in (0, 90) else "3 5"}"/>')
    for i, (name, note, per, tot, wins) in enumerate(rows):
        y = top + i * rh
        nagi = name.startswith("Nagi-ENORMOUS")
        col = GRN if nagi else MUT
        body.append(f'<text x="36" y="{y+24}" fill="{BONE}" font-family="{BODY}" font-size="19" font-weight="{800 if nagi else 600}">{esc(name)}</text>'
                    f'<text x="36" y="{y+44}" fill="{MUT}" font-family="{MONO}" font-size="12">{esc(note)}</text>')
        body.append(f'<rect x="{x0}" y="{y+8}" width="{90*scale}" height="30" fill="{PANEL}"/>')
        x = x0
        for k, p in enumerate(per):
            w = p * scale
            if w:
                body.append(f'<rect x="{x:.1f}" y="{y+8}" width="{w:.1f}" height="30" fill="{col}" fill-opacity="{TINT[k]}"/>')
                if w > 26:
                    body.append(f'<text x="{x + w/2:.1f}" y="{y+28}" text-anchor="middle" fill="{INK}" font-family="{MONO}" font-size="13" font-weight="700">{p}</text>')
                x += w
                body.append(f'<rect x="{x-1.5:.1f}" y="{y+8}" width="3" height="30" fill="{INK}"/>')
        body.append(f'<text x="{x1+18}" y="{y+30}" fill="{GRN if nagi else BONE}" font-family="{MONO}" font-size="24" font-weight="700">{tot}<tspan fill="{MUT}" font-size="14">/90</tspan></text>'
                    f'<text x="{x1+18}" y="{y+50}" fill="{MUT}" font-family="{MONO}" font-size="12">{wins}/30 round wins</text>')
    h = top + rh * len(rows) + 30
    body.append(f'<text x="36" y="{h-14}" fill="{MUT}" font-family="{MONO}" font-size="12">3/2/1/0 points per round · 10 rounds per game · lockstep · same seeds · 2026-09-25</text>')
    lead = rows[0]
    svg = frame(h, title, kicker, "".join(body), tape(W - 250, 30, f"#1 · {lead[3]}/90"))
    open(os.path.join(OUT, fn), "w").write(svg)


def airborne_chart(fn, results, roster):
    m = results["rotorwash"]["models"]
    rows = sorted(((name, m[key]["survival_s"]) for key, name, _ in roster), key=lambda r: -st.median(r[1]))
    x0, x1, top, rh = 200, W - 150, 170, 58
    vmax = 90
    sc = (x1 - x0) / vmax
    body = [f'<text x="{x0}" y="146" fill="{MUT}" font-family="{MONO}" font-size="12" letter-spacing="1">BAR = MEDIAN · TICKS = EACH OF 10 ROUNDS · SECONDS AIRBORNE (CAP 90 S)</text>']
    for v in range(0, 91, 30):
        x = x0 + v * sc
        body.append(f'<line x1="{x}" x2="{x}" y1="{top-8}" y2="{top + rh*len(rows) - 14}" stroke="{LINE}" stroke-dasharray="{"" if v in (0, 90) else "3 5"}"/>'
                    f'<text x="{x}" y="{top + rh*len(rows) + 4}" text-anchor="middle" fill="{MUT}" font-family="{MONO}" font-size="12">{v}s</text>')
    for i, (name, xs) in enumerate(rows):
        y = top + i * rh
        nagi = name.startswith("Nagi")
        col = GRN if nagi else MUT
        med = st.median(xs)
        body.append(f'<text x="36" y="{y+27}" fill="{BONE}" font-family="{BODY}" font-size="18" font-weight="{800 if nagi else 600}">{esc(name)}</text>'
                    f'<rect x="{x0}" y="{y+10}" width="{med*sc:.1f}" height="24" fill="{col}" fill-opacity="{1 if nagi else .55}"/>')
        for v in xs:
            body.append(f'<rect x="{x0 + v*sc - 1:.1f}" y="{y+4}" width="2" height="36" fill="{BONE}" fill-opacity=".85"/>')
        body.append(f'<text x="{x1+18}" y="{y+29}" fill="{GRN if nagi else BONE}" font-family="{MONO}" font-size="20" font-weight="700">{med:.1f}<tspan fill="{MUT}" font-size="13"> s</tspan></text>')
    h = top + rh * len(rows) + 50
    body.append(f'<text x="36" y="{h-14}" fill="{MUT}" font-family="{MONO}" font-size="12">Points tie with Jev (25–25; ranked by distance) · airborne longer than Jev in 9/10 rounds, sign test p = 0.02</text>')
    svg = frame(h, "Rotorwash: who stays up", "Arena Live · 240 Hz helicopter", "".join(body), stamp(W - 210, 34, "9/10 VS JEV"))
    open(os.path.join(OUT, fn), "w").write(svg)


def public_chart(fn):
    # common-evidence eight-source macro, 4,518 rows (bench/HUGE_PUBLIC.md, docs/ENORMOUS_RELEASE.md)
    rows = [("Jev 1.13.0", 83.95, False), ("Nagi-ENORMOUS 27B", 82.76, True), ("Nagi-HUGE 12B", 77.49, True),
            ("OpenJev / SemIf", 73.87, False), ("Laya", 57.35, False)]
    x0, x1, top, rh = 250, W - 150, 170, 52
    sc = (x1 - x0) / 100
    body = [f'<text x="{x0}" y="146" fill="{MUT}" font-family="{MONO}" font-size="12" letter-spacing="1">ACCURACY, 0–100 % · 8 PUBLIC SOURCES, EQUAL WEIGHT · 4,518 ROWS</text>']
    for v in (0, 25, 50, 75, 100):
        x = x0 + v * sc
        body.append(f'<line x1="{x}" x2="{x}" y1="{top-8}" y2="{top + rh*len(rows) - 12}" stroke="{LINE}" stroke-dasharray="{"" if v in (0, 100) else "3 5"}"/>'
                    f'<text x="{x}" y="{top + rh*len(rows) + 6}" text-anchor="middle" fill="{MUT}" font-family="{MONO}" font-size="12">{v}</text>')
    for i, (name, v, nagi) in enumerate(rows):
        y = top + i * rh
        flag = name.startswith("Nagi-ENORMOUS")
        col = GRN if nagi else MUT
        body.append(f'<text x="36" y="{y+25}" fill="{BONE}" font-family="{BODY}" font-size="18" font-weight="{800 if flag else 600}">{esc(name)}</text>'
                    f'<rect x="{x0}" y="{y+8}" width="{v*sc:.1f}" height="24" fill="{col}" fill-opacity="{1 if flag else (.6 if nagi else .55)}"/>'
                    f'<text x="{x1+18}" y="{y+27}" fill="{GRN if flag else BONE}" font-family="{MONO}" font-size="19" font-weight="700">{v:.2f}<tspan fill="{MUT}" font-size="13">%</tspan></text>')
    h = top + rh * len(rows) + 52
    body.append(f'<text x="36" y="{h-14}" fill="{MUT}" font-family="{MONO}" font-size="12">ENORMOUS − Jev = −1.20 pp, 95% CI [−2.70, +0.31]: statistically tied · public subsets, not official leaderboard scores</text>')
    svg = frame(h, "Public suite: tied with Jev", "Static decision benchmark · 4 systems + ENORMOUS", "".join(body), stamp(W - 150, 34, "TIED"))
    open(os.path.join(OUT, fn), "w").write(svg)


def main():
    os.makedirs(OUT, exist_ok=True)
    B = os.path.join(ROOT, "bench", "arena_live")
    vend = json.load(open(os.path.join(B, "results_vendors.json")))
    lines = json.load(open(os.path.join(B, "results_nagi_lines.json")))
    vroster = [("Nagi-ENORMOUS", "Nagi-ENORMOUS", "27B · open weights"), ("Jev", "Jev 1.13.0", "API"),
               ("SemIf", "OpenJev", "SemIf · Qwen3.5-4B"), ("Laya", "Laya", "router v0.3.20")]
    nroster = [("Nagi-ENORMOUS", "Nagi-ENORMOUS", "27B"), ("Nagi-HUGE", "Nagi-HUGE", "12B"),
               ("Nagi-BIG", "Nagi-BIG", "4B"), ("Nagi-SMOL", "Nagi-SMOL", "0.5B")]
    arena_chart("arena_vendors.svg", vend, vroster, "Arena Live: first place", "3 real-time games · ENORMOUS vs Jev, OpenJev, Laya")
    arena_chart("arena_nagi_lines.svg", lines, nroster, "Bigger line, better play", "Arena Live · the four Nagi lines")
    airborne_chart("rotorwash_airborne.svg", vend, vroster)
    public_chart("public_suite.svg")
    print("wrote", sorted(os.listdir(OUT)))


if __name__ == "__main__":
    main()
