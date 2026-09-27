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
| `RELEASE_DATE` | hero tape | publish date | `28 Sep 2026` |
| `BURST_VARIANT` | latency table, gates caption, limitations | offline-gates receipt → selected variant (frozen rule, never Arena outcomes) | `A, canonical order` or `B, permutation-averaged` |
| `P2_N_SEEDS` | hero key sentence | PREREG / P2 results.json → number of fresh seed indices per game | `NN` |
| `P2_SEED_RANGE` | confirmation paragraph | P2 results.json → seed index range | `NN–NN` |
| `P2_WINRATE_VS_JEV`, `P2_WINRATE_VS_JEV_CI` | hero, claims, gates table | P2 results.json → composite paired per-seed win rate Burst vs Jev, 95% CI over seed indices | `NN%`, `[NN%, NN%]` |
| `P2_WINRATE_VS_KCALL`, `P2_WINRATE_VS_KCALL_CI` | hero, claims, gates table | P2 results.json → same, Burst vs K-call (same weights) | as above |
| `P2_BURST_P50_MS`, `P2_KCALL_P50_MS`, `P2_LAT_RATIO` | hero facts, latency table | P2 results.json → decision latency p50, Rotorwash-Ramp, release serving path, 3 streams per H100; ratio = Burst/K-call p50 (2 decimals) | `NNN`, `NNN`, `0.NN` |
| `P2_ORDER_FLIP_RATE`, `P2_ORDER_FLIP_CI` | hero facts, gates, limitations | offline-gates receipt → order-sensitivity flip rate of the selected variant, family-bootstrap 95% CI | `N.N%`, `[N.N%, N.N%]` |
| `PREREG_ORDER_LIMIT` | hero facts, gates, limitations | PREREG.md → order gate threshold | `NN%` |
| `P2_ORDER_VERDICT`, `P2_MA1_VERDICT`, `P2_KCALL_VERDICT`, `P2_JEV_VERDICT`, `P2_VOID_VERDICT` | gates table | the release report's verdict column, verbatim | `PASS` |
| `P2_MA1_DELTA`, `P2_MA1_CI`, `PREREG_MA1_RULE` | gates table | offline-gates receipt → MA1 Burst − K-call; PREREG rule text | `+0.NNN`, `[−0.NNN, +0.NNN]`, rule text |
| `PREREG_KCALL_RULE`, `PREREG_JEV_RULE` | gates table | PREREG.md → the realtime rules, short form | rule text, short |
| `P2_VOID_ROUNDS` | gates table | P2 results.json → void rounds (all cells) | `N of NNN` |
| `P2_JEV_SENTENCE` | Jev section | P2 results.json, Jev cells on fresh seeds: one factual sentence (Jev p50, fresh share, win rate); delete the `<p>` if not needed | sentence |
| `P2_CHART_NOTE` | data.json → confirmation.note | design line: seeds, players, variant, source file + sha256 | sentence |
| `P2_RESULTS_SOURCE` | data.json → confirmation_schema | remove the `confirmation_schema` block once `confirmation` is filled | – |
| `CLIP_SEED_SNAKE`, `CLIP_SEED_RR`, `CLIP_SEED_BG` | clip captions | render job log / `showcase_players` rule output → seed index shown in each clip | `N` |
| `SDK_TAG` | reproduce | nagi-public tag or commit that ships `mode="burst"` (burst_config.json: sdk_min_version 0.6.0) | tag or short sha |
| `SDK_BURST_SNIPPET` | reproduce | the public SDK call, tested on the published weights (loader name + `system_one(..., mode="burst")`) | 4–8 lines of Python, HTML-escaped |
| `URL_HF_BURST` | hero button, links | final HF repo (draft name `nagisanzeninz/Nagi-ENORMOUS-Burst`), must be PUBLIC | URL |
| `URL_REPORT` | hero button, links | public report with every number + receipts + sha256 (suggested `https://github.com/nagisanzenin/nagi/blob/main/bench/burst/README.md`) | URL |
| `URL_PREREG` | confirmation, links | public copy of PREREG.md with its commit hash (suggested `bench/burst/PREREG.md`) | URL |
| `URL_PROTOCOL` | links | public copy of Arena v3 PROTOCOL.md (suggested `bench/arena_v3/PROTOCOL.md`) | URL |
| `URL_RECORDS` | links | public round records (V2 format) + replay instructions (suggested `bench/burst/records/` or an HF dataset) | URL |

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
- [ ] The "What we claim" box is still true with the filled numbers (e.g. if P2 vs K-call is not significant, the
      third claim must be rewritten to what the CI supports, or the release does not happen per PREREG).
- [ ] The hero facts use the release variant's numbers, not Board 1's prototype.
- [ ] Glossary: confirm "ENORMOUS (previous)" = the adapter published as `nagisanzeninz/Nagi-ENORMOUS` revision
      `2e03ec38…`; if yes, you may call it "Nagi-ENORMOUS (released 25 Sep)" in the tables and data.json labels.
- [ ] If variant B is selected: the latency row and the hero latency must be B's own measurement (B processes K× the
      tokens of A), and the "tokens processed" row of the comparison table should gain a B column (≈ K × (S + K·q)).
- [ ] Owner decision: the og/twitter description is number-free now; optionally add the headline P2 number.
- [ ] Variant B text ("all K rotations") matches the frozen implementation (cyclic orbit vs all K! orders).
- [ ] No "Chord" outside the history paragraph, the latency-table note and the glossary; no "T-dual" outside the glossary.

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
