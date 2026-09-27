# Burst landing page: publish checklist

Page: `site/burst/` (index.html, burst.js, data.json; share.png and media/ to add). Branch `burst-page`.
Tool: `python3 scripts/burst_page.py check | fill values.json | preview`.
Guard: `.github/workflows/pages.yml` runs `check` before every deploy, so a merge with any `{{PLACEHOLDER}}` left
under `site/` fails the deploy instead of publishing it. Do not merge `burst-page` into `main` before this list is done.

Publishing rule (docs/burst_release/APPROVAL.md in nagi-research, owner 2026-09-27 ~17:40): publish only if EVERY gate
and release rule in `docs/burst_release/PREREG.md` passes. If any fails, the page is not published at all; it is not
rewritten around a failure.

## 1. Placeholders

Every value is copied from a receipt, never computed by hand or rounded differently from the receipt. "P2" = the
Burst release realtime confirmation on fresh seeds; "offline gates" = the P1 stage of the Burst release plan.
Exact receipt paths are fixed by the release operator; write them into the report linked as `URL_REPORT`.

| Placeholder | Where | Source (file → field) | Format (shape only, not a value) |
|---|---|---|---|
| `RELEASE_DATE` | hero tape | publish date | `DD Mon 2026` |
| `BURST_VARIANT` | gates caption, limitations | `docs/burst_release/selection.json` → SELECT (PREREG §5) | `A (canonical order)` / `B (cyclic orbit)` |
| `G1_SDK_RESULT`, `G1_SDK_VERDICT` | gates | offline-gates receipt → G1-SDK for the counted variant (PREREG §3.1) | `500 / 500`, verdict |
| `PHI_A`, `PHI_A_CI` | hero facts, gates, limitations | offline-gates receipt → φ_A (model-level flips without canonicalization, serving path) + two-stage 95% CI | `NN.N%`, `[NN.N%, NN.N%]` |
| `G1B_PHI`, `G1B_UB`, `G1B_VERDICT` | gates | offline-gates receipt → G1-B (variant B, measured even if A is selected) | `N.N%`, `N.N%`, verdict |
| `G2_DELTA`, `G2_BOUND`, `G2_VERDICT` | hero facts, gates | offline-gates receipt → G2 for the counted variant: Δ̂ MA1 and L = min(bootstrap, t12) | `+0.NNN`, `−0.NNN`, verdict |
| `G3_DELTA`, `G3_UB`, `G3_VERDICT` | gates | offline-gates receipt → G3 Δ_U and t upper bound | `+0.NNN`, `0.NNN`, verdict |
| `LAT_P50_MS_SNAKE`, `LAT_P50_MS_RR`, `LAT_P50_MS_BG`, `LAT_UB_MS_*`, `LAT_VERDICT` | hero, facts, claims, latency table, gates | offline-gates receipt → LAT probe p50 and one-sided 97.5% upper bound per game, 3 streams (PREREG §3.4) | integers in ms, verdict |
| `P2_VOID_ROUNDS`, `V_RT_VERDICT` | gates | P2 analysis → void rounds over all P2 cells; V_rt (PREREG §6.1) | `N of NNN`, verdict |
| `P2_WINRATE_VS_JEV`, `P2_WINRATE_VS_JEV_CI` | hero, claims, gates, Jev section | P2 analysis → Θ (composite paired win rate vs Jev, indices 10–33) and its 95% t CI (PREREG §6.2–6.4) | `NN%`, `[NN%, NN%]` |
| `R_RT_VERDICT` | gates | P2 analysis → R-RT | verdict (must be PASS to publish) |
| `C1_P`, `C1_VERDICT`, `P2_C1_CLAUSE` | gates, hero | P2 analysis → C1 sign-flip p and verdict. Clause: `""` unless C1 passed, then `, a preregistered superiority result` | `0.NNNN`, verdict, text |
| `C2_WINRATES`, `C2_VERDICTS` | gates | P2 analysis → W_g per game and Holm verdicts (only if C1 passed; else `not tested`) | `NN% / NN% / NN%` |
| `P2_CHART_NOTE` | data.json → confirmation.note | design line for the fresh-seed chart: indices, players, variant, source + sha256 | sentence |
| `P2_RESULTS_SOURCE` | data.json → confirmation_schema | remove the whole `confirmation_schema` block once `confirmation` is filled | – |
| `CLIP_SEED_SNAKE`, `CLIP_SEED_RR`, `CLIP_SEED_BG` | clip captions | render job log (fixed seed rule, PROTOCOL A1.5) → seed index per clip | `N` |
| `SDK_TAG` | reproduce | nagi-public tag/commit that ships Burst (burst_config.json: sdk_min_version 0.6.0) | tag or sha |
| `SDK_BURST_SNIPPET` | reproduce | the public SDK call, tested against the published weights. The model-card draft (burst-package `MODEL_CARD.md` § Use) uses `from nagi import load_enormous_burst` and `nagi.system_one(state, questions, mode="burst")`; copy the final, tested version | 4–8 lines, HTML-escaped |
| `URL_HF_BURST` | hero, links | final HF repo (draft `nagisanzeninz/Nagi-ENORMOUS-Burst`), PUBLIC | URL |
| `URL_REPORT` | hero, links | public report with every number, receipts, sha256 (suggested `bench/burst/README.md` in nagi-public) | URL |
| `URL_PREREG` | gates paragraph, links | public copy of PREREG.md (frozen `f0d6204` + Amendment 1 `0c346f5` in nagi-research) | URL |
| `URL_PROTOCOL` | links | public copy of Arena v3 PROTOCOL.md | URL |
| `URL_RECORDS` | links | public round records + replay instructions | URL |

Also fill `site/burst/data.json → confirmation` with the P2 per-round survival times, in the same shape as `board1`
(`source`, `design`, `note`, `cap_s`, `death_s{game:{player:[seconds per seed index]}}`, `latency_p50_ms`,
`fresh_share`; player id of the release readout: `burst`). The chart then defaults to the confirmation data.

HTML comments starting with `PH` in index.html mark each block; delete them after filling if you like (they are not
visible, but they are public in the page source).

## 2. Assets (operator TODO)

- [ ] `site/burst/media/burst-snake-rush.mp4`, `burst-rotorwash-ramp.mp4`, `burst-booster-gauntlet.mp4`: the
      Burst-labelled release clips (they replace `~/Downloads/Nagi-ArenaV3-{SnakeRush,RotorwashRamp,BoosterGauntlet}.mp4`,
      whose labels say "T-dual Chord"). Re-encode for the web (H.264, `-movflags +faststart`, ≤ 8 MB each; the site is
      served from the repo, so keep total media small) and check with ffprobe.
- [ ] Posters `site/burst/media/burst-*.jpg` (a representative frame, 540×960).
- [ ] Clips must show the name "Burst" (never "Chord" or "T-dual Chord") and follow the fixed seed rule (PROTOCOL A1.5).
- [x] `site/burst/share.png` 1200×630, rendered from `docs/burst/share.html` (§4). It is deliberately number-free,
      so it needs no update unless the headline changes.

## 3. Checks before going live

Numbers and claims
- [ ] `python3 scripts/burst_page.py check` prints `OK`.
- [ ] Every filled number matches its receipt exactly (spot-check at least the hero, gates table and latency row).
- [ ] Every PREREG gate passed. If one failed: do not publish (APPROVAL.md).
- [ ] Every sentence in "What we claim" is allowed by PREREG §8.2 for the tests that passed; nothing on the page
      uses a §8.2 "never allowed" claim (0–9 beyond screen, lockstep claims, order-invariant model for A, K ≥ 5,
      other games, Jev size/hardware, P1 REJECT-ORDER or A1 passed).
- [ ] The hero facts use the counted variant's gate numbers, not Board 1's.
- [ ] If SELECT = B: rewrite the "Control order" hero tile and the limitations item with the PREREG §8.2 B wording
      (order residual φ_B ≤ 10% for K ≤ 3, K = 4 not gated), add "M = K orders batched" to the design statement, and
      relabel the Board 1 Burst row (it is variant A's player, not B's).
- [ ] If C1 failed: `P2_C1_CLAUSE` is empty and no sentence says "better than" or "outperforms" Jev (PREREG §9).
- [ ] If the G3 realtime pathology flag triggered (≥ 50% of fresh Rotorwash-Ramp rounds end on the ceiling), add it
      to the limitations (PREREG §3.3).
- [ ] Latency source: the page uses pooled p50 over all requests (player_summary.json), which is what PREREG quotes;
      the Board 1 report's table uses the median of per-round p50s (Burst 227/242/249 ms). Keep one definition per
      table and say which.
- [ ] Confirm the label "Nagi-ENORMOUS (released)": research name ENORMOUS-old = the public adapter
      `nagisanzeninz/Nagi-ENORMOUS` revision `2e03ec38…` (step 500), which the Burst model card says the Burst weights
      continue from. If not, relabel it in index.html (Board 1 table, table view, glossary) and data.json.
- [ ] Owner decision: the og/twitter description is number-free now; optionally add the headline P2 number.
- [ ] No "Chord" outside the history paragraph and the glossary; no "T-dual" outside the glossary.

Links
- [ ] Every `{{URL_*}}` resolves publicly (logged out): HF repo public, GitHub files merged to `main`.
- [ ] No link into the private nagi-research repo (visitors get 404s; see site commit f83f73a).
- [ ] `../arena/` shows the Arena v3 board (branch `arena-v3-site`); if its anchors change, update the links.

Page
- [ ] `python3 site/build_chrome.py` re-run after merging with `arena-v3-site` (both branches touch the chrome
      builder, home page and nav; resolve conflicts, then re-stamp every page).
- [ ] Open locally (`python3 -m http.server -d site 8000`, then /burst/): desktop 1280 px and phone 375 px, no
      horizontal page scroll, chart renders for all 3 games and both datasets, table view present, videos play.
- [ ] OG card: paste the URL into a card validator after deploy (Twitter/X, LinkedIn post inspector, or
      `curl -s URL | grep og:`), and check that share.png loads (absolute URL).
- [ ] `docs/burst/share.html` is a generator only; `site/` contains no draft or private files.

## 4. Share image

`docs/burst/share.html` is a 1200×630 page in the site's style, with no numbers. Re-render after editing it:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --hide-scrollbars \
  --window-size=1200,630 --screenshot=site/burst/share.png docs/burst/share.html
```
