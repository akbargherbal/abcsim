# abcsim follow-up plan: handoff 0.2.3 fixes

**Audience:** the AI agent that maintains `akbargherbal/abcsim`.
**Base:** commit `9480245` ("Add project README"), handoff folder `handoff/skill_0.2.3/`.
**Why this exists:** while planning the integration into `abc_score_composer` (Repo B), several problems in abcsim's handoff were found. This plan fixes them at the source so Repo B does not need workarounds.
**Out of scope:** any change to Repo B. You still only produce files under `handoff/`.

## Status (updated 2026-11-27)

All 8 phases are complete on branch `recover-claude-0.2.3-r2` (tagged `handoff-0.2.3-r2`).

| Phase | State | Evidence / what was shipped |
|---|---|---|
| 1. Mode audit | **done** | `abcsim/audit_modes.py`, `out/mode_audit.md`; **2,249 of 21,396 candidates (10.5%) contain `b2`**. |
| 2. Classifier | **done** | Two-stage rule with `MAQAM_TEMPLATES` (`core`/`tolerated`/`branch`/`requires_all`/`requires_any`), `MIN_MODE_NOTES = 6`, `MIN_MODE_SHARE = 0.70`. `tests/test_mode_hint.py` (15 pass). **4,232 of 21,396 (19.8%) changed label.** P010 `saba-like` -> `kurd-like`. |
| 3. Mode quotas | **done** | `--min-per-mode` / `--modes`, `counts.mode_shortfall`. Bank: kurd 8, hijaz 8, rast 8, nahawand 15, bayati 1 (shortfall explicit: wanted 8, got 1), minor 6, major 2. 48 phrases, 24/24 cadence classes. |
| 4. Byte budget | **done** | `phrase_bytes`, `fits_seed_budget`, `--max-phrase-bytes` (default 130), `schema: "phrase_bank/2"`, selection metadata under `generated_from.selection`. Bank is **45 x 8-beat and 3 x 16-beat**; `INTEGRATION.md` recommends 8-beat seeds only. |
| 5. Fingerprints | **done** | `--budget-bytes`, `--sketch-k`, sketch-aware `novelty_check.py`, `docs/fingerprint_options.md`. Default `bottom-256` (630,382 B @0.08); `full` (1,027,911 B @0.08), `k512` (984,499 B @0.08), `k128` (334,812 B @0.15), `k64` (181,817 B @0.15) all in `handoff/skill_0.2.3/assets/alt/`. |
| 6. Portability/docs | **done** | `abcsim/repo_b.py`, `grep -rn "/tmp/" abcsim tests` empty; F6 no-key seed example + tonic-relative note, F7 re-measure instruction + discrepancy note, F10 `status=close`-only compact card, honest limitations, and `handoff/skill_0.2.3/HANDOFF_REVISION.md`. |
| 7. Tests | **done** | `tests/conftest.py`, `test_mode_hint.py`, extended `test_phrases.py` / `test_assets_size.py` / `test_novelty.py`, isolated `test_clusters_seed.py` write test to `tmp_path`. **38 passed, 4 skipped** without Repo B, verified from a clean clone. |
| 8. Release | **done** | Sketch-aware `calibrate_novelty.py` regenerated `docs/novelty_calibration.md` & `out/novelty_calibration.json` for `bottom-256` @0.08 (excluding vocal-only clusters `C020`/`C042` documented), full export regenerated, `docs/FINAL_REPORT.md` Revision 2 table added, tagged `handoff-0.2.3-r2`. |

## 0. Findings (verified unless marked otherwise)

| # | Finding | Evidence |
|---|---|---|
| F1 | **Maqam classifier is biased toward large scales.** `mode_hint()` in `abcsim/export_phrases.py` scores each template by the share of the phrase's notes whose pitch class is in the template, and the best share wins. The Kurd template is `[0,1,3,8,10]`, which omits pitch classes 5 and 7 (degrees 4 and 5), so any Kurd phrase that uses 4 or 5 loses points. The nahawand template has 7 pitch classes and wins whenever a phrase has no `b2`. | Source of `MAQAM_TEMPLATES`. Example: bank phrase P010 uses `1 4 b2 b3 b6 b7` and is labeled `saba-like`. |
| F2 | **The bank has almost no Kurd.** `by_mode_hint`: nahawand-like 39, rast-like 4, major-like 2, kurd-like 1, bayati-like 1, saba-like 1. Only 3 of 48 phrases contain `b2`; 37 contain a natural `2`. | `phrase_bank.json` |
| F3 | **Selection never targets mode.** `select_diverse()` runs per cadence class only, farthest-point over a phrase vector, so rare modes are not protected. | `export_phrases.py` lines about 262-296 |
| F4 | **Part of F2 is the data.** The corpus is almost all minor keys (Cm 101, Gm 89, Em 74, Am 71, Dm 67 ...). So Kurd-shaped phrases may genuinely be rare. **Not yet measured:** how many of the 21,396 candidates contain `b2`, and how many would be Kurd-like under a corrected classifier. | `corpus_profile.json` keys; candidate count from `phrase_bank.json` |
| F5 | **Seed length budget is not met.** Phrase text ranges 29 to 275 B (median 105 B) but the handoff tells Repo B to print up to three seeds in 400 B. | `phrase_bank.json` |
| F6 | **`INTEGRATION.md` example is misleading.** It shows `SEED P012 sadr 16 beats Gm ...`; degrees are tonic-relative, so printing a source key suggests a transposition that does not exist. | `handoff/skill_0.2.3/INTEGRATION.md` |
| F7 | **Footprint numbers conflict with Repo B.** Handoff docs say SKILL.md 5,824 B, mandatory reading 26,484 B, inspector cards 11 / 20 words. Repo B's own 0.2.2 changelog says 5,808 B, 26,468 B, 13 / 32 words. | `CHANGELOG_SNIPPET.md`, `INTEGRATION.md` vs Repo B `CHANGELOG.md` |
| F8 | **The fingerprint file does not compress** (1,027,894 B becomes 1,003,984 B under zlib), so Repo B's package would grow from about 80 KB to about 1.1 MB. A bottom-k sketch exists in `export_fingerprints.py` but only as an automatic fallback when a size budget is exceeded; there is no CLI control. | `export_fingerprints.py` lines about 89-100 |
| F9 | **Hardcoded local path.** `calibrate_novelty.py` defaults `--example` to `/tmp/opencode/abc_score_composer/assets/example_song.abc`, and `tests/test_phrases.py` has the same path in its search list. These break on other machines, including the user's Windows setup. | argparse defaults and `find_repo_b()` |
| F10 | **Novelty line would grow Repo B's success card** if printed always (the handoff claims no word growth). | `INTEGRATION.md` section 2 |

## 1. Ground rules

- Keep the pipeline reproducible: every output is regenerated from the corpus zip plus committed code.
- Do not change existing numeric outputs silently. Any change to `phrase_bank.json`, `corpus_fingerprints.bin`, or the calibration doc must be called out in the new handoff changelog with before/after numbers.
- Keep the handoff folder layout. Repo B's maintainer already has a plan referencing it. Bump the handoff folder name to `handoff/skill_0.2.4/` only if file names change; otherwise update in place and add a `HANDOFF_REVISION.md` with a revision number and commit hash.
- Do not edit the corpus zip.
- Cross-platform: no `/tmp/...` defaults, use `pathlib`, UTF-8, environment variable overrides.

## 2. Phase 1: measure first (answers F4)

Do this before touching the classifier, so the fix is judged against real numbers.

1. Write `abcsim/audit_modes.py`. It loads the same candidates `export_phrases.py` builds (reuse its candidate generator; do not fork the logic) and writes `out/mode_audit.md` with:
   - candidate counts by current `mode_hint`;
   - candidate counts with `b2` present, with `b2` and `b3`, with `b2` and `b6` or `b7`;
   - for songs: key tonic mode (minor/major) and how often `b2` appears in the whole vocal stream, as a per-song histogram;
   - a table of 20 random candidates with their degree sets and current label, for human review.
2. Record the result in the report. This quantifies how much of F2 is data and how much is classifier.

**Acceptance:** `out/mode_audit.md` exists and states the number of candidates that contain `b2`.

## 3. Phase 2: fix the maqam classifier (F1)

**File:** `abcsim/export_phrases.py`.

1. Replace the templates with full scale-tone sets, in pitch classes relative to the tonic:
   - `kurd-like`: `{0,1,3,5,7,8,10}`
   - `hijaz-like`: `{0,1,4,5,7,8,10}` (approximation of the Hijaz scale on the tonic)
   - `nahawand-like`: `{0,2,3,5,7,8,10}` (natural minor) with harmonic-minor tolerance for `7`
   - `rast-like`: `{0,2,4,5,7,9,10}` (neutral 3rd approximated)
   - `bayati-like`: `{0,1,3,5,7,9,10}` (with `b2` and a minor or neutral 3rd approximated as `b3`)
   - `saba-like`: `{0,1,3,4,6,8,10}`
   - `major-like`: `{0,2,4,5,7,9,11}`
   Document each template's source and approximation in a comment. If the existing skill file `references/maqam.md` has a stricter definition, follow it and cite it.
2. Replace "highest share wins" with a two-stage rule:
   1. **Distinguishing-degree rules first.** Presence of `b2` (pitch class 1) narrows the candidates to kurd, hijaz, bayati, saba; presence of a natural `2` (pitch class 2) narrows to nahawand, rast, major. Then `b3`/`3` and `b6`/`6` split further.
   2. Within the surviving set, score by share of notes inside the template, then break ties by fewer unused template tones (prefer the tighter fit).
3. When the evidence is thin (fewer than about 6 notes, or no distinguishing degree present), return `minor-like` or `major-like`, not a specific maqam. A phrase with no `b2` and no `2` is ambiguous; say so in the label instead of guessing nahawand.
4. Add a unit test file `tests/test_mode_hint.py` with hand-written cases: a Kurd phrase using `1 4 5 b2 b3`; a nahawand phrase with natural `2` and `b6`; a Hijaz phrase with `b2` and natural `3`; a phrase with only `1 b3 5` (must be `minor-like`); and P010's degrees (must no longer be `saba-like` unless it contains the Saba-specific `b5` with `3`, which it does not).
5. Re-label all 21,396 candidates and print the old-versus-new confusion matrix to `out/mode_audit.md`.

**Acceptance:** tests pass; confusion matrix shows which phrases changed; P010 is reclassified (document the new label).

## 4. Phase 3: selection that protects rare modes (F3)

**File:** `export_phrases.py` (`select_diverse`, `main`).

1. Add `--min-per-mode N` (default 4) and `--modes kurd-like,hijaz-like,bayati-like,rast-like,nahawand-like` (the modes Repo B's intake recognizes).
2. Selection order per cadence class:
   1. For each requested mode, pick up to `N` phrases via farthest-point **within that mode's candidates**.
   2. Fill the remaining slots with farthest-point over all candidates, preserving the existing caps (one per cluster, at most 3 per source song).
3. If a mode has fewer than `N` candidates, take what exists and print a clear warning in the export log and in `phrase_bank.json` under `counts.mode_shortfall` (for example `{"kurd-like": {"wanted": 4, "got": 1}}`). Do not pad with mislabeled phrases.
4. Keep total size at most 60 KB and total phrases per cadence class between 20 and 28.

**Acceptance:** the bank's `by_mode_hint` shows at least the shortfall-reported minimum for every requested mode; any shortfall is explicit, not silent.

## 5. Phase 4: phrase metadata Repo B needs (F5)

1. Add `phrase_bytes` (UTF-8 length of the `phrase` string) to every phrase.
2. Add `fits_seed_budget` (bool): `phrase_bytes <= 130`. Print counts of fitting and non-fitting phrases per cadence class and per mode.
3. Add an `--max-phrase-bytes` option (default none). When set, candidates over the limit are excluded before selection. Recommend in the handoff to run with `--max-phrase-bytes 130` so every phrase can actually be printed as a seed. Decide the default after seeing how many 16-beat phrases survive; if fewer than 6 of them fit, say so in `INTEGRATION.md` and recommend printing 8-beat seeds only.
4. Bump the bank's `schema` string (for example `phrase_bank/2`) and list the new fields in the file's `grammar` block so a reader can detect the version.

**Acceptance:** every phrase carries `phrase_bytes`; a documented, reproducible command produces a bank whose phrases all fit the seed budget, or the shortfall is stated.

## 6. Phase 5: fingerprint size control (F8)

1. Add `--budget-bytes N` and `--sketch-k K` to `export_fingerprints.py`. `--sketch-k` forces a bottom-k sketch per song regardless of budget.
2. Run three variants and record, for each, file size and the calibration results from `calibrate_novelty.py` (positives caught, false-positive rate on unrelated pairs, max unrelated containment): full set; bottom-k with k = 512; k = 128 (adjust the values if they do not span a useful size range).
3. Write the comparison to `docs/fingerprint_options.md`. Include a recommendation on which variant gives the best trade-off, and recompute the threshold per variant. Do not reuse 0.05 without re-checking.
4. Emit the chosen variant's file and the other variants under `handoff/skill_0.2.3/assets/alt/` (not loaded by default). Repo B's maintainer picks one.

**Acceptance:** all three variants have calibration numbers; the recommendation names a threshold per variant; `novelty_check.py` loads each variant (it must read the header's `sketch` flag; if it does not already support sketches, add that and cover it with a test).

## 7. Phase 6: portability and documentation fixes (F6, F7, F9, F10)

1. **Paths (F9):** in `calibrate_novelty.py` and `tests/test_phrases.py`, remove every `/tmp/...` default. Resolve Repo B via the `ABC_SCORE_COMPOSER` environment variable, then sibling folder, then home folder; skip tests cleanly when absent, and exit with a clear message in the CLI.
2. **Seed example (F6):** correct `INTEGRATION.md`. The example line must not include a key: `SEED P012 sadr 16b 4:.5 5:1 b3:.5 ...`. State explicitly that degrees are tonic-relative.
3. **Footprint (F7):** remove the hardcoded 0.2.2 numbers from `INTEGRATION.md` and `CHANGELOG_SNIPPET.md`. Replace them with: "Re-measure with Repo B's `scripts/measure_footprint.py` on the target commit; the abcsim handoff adds no mandatory reading." Keep a note of the discrepancy found (5,824 B versus 5,808 B).
4. **Success-card growth (F10):** change the novelty guidance to "print the compact-card line only when `status=close`; always print in verbose mode".
5. **Honest limitations section:** in `INTEGRATION.md`, add a short section listing what the assets do **not** show: seeds are unproven to improve generation; `role_hint` is heuristic; the bank is mid/high register only; the corpus is AI-generated Suno output transcribed by SheetSage2; exact 8-gram matching misses rhythmically varied copies (1 of 47 cluster pairs under threshold).
6. Add `HANDOFF_REVISION.md` listing the revision, the abcsim commit, and a table of what changed from commit `9480245`.

**Acceptance:** `grep -rn "/tmp/" abcsim tests` returns nothing; docs no longer contain the 5,824 B figure as a baseline; the seed example has no key.

## 8. Phase 7: tests

Add or extend under `tests/`:

- `test_mode_hint.py`: Phase 2 cases above.
- `test_phrases.py`: keep the round-trip check; add that every phrase has `phrase_bytes`, that `fits_seed_budget` agrees with the length, and that `counts.mode_shortfall` is present when a mode is below target.
- `test_assets_size.py`: bank at most 60 KB; each fingerprint variant at most its documented size; the default variant at most 1.1 MB.
- `test_novelty.py`: all fingerprint variants load; for each variant, a known cluster pair is flagged and a known unrelated pair is not.
- Keep every existing test green. Run the whole suite from a clean checkout.

## 9. Phase 8: regenerate and publish

1. Re-run the full export from the corpus zip, in the order: clusters (unchanged unless Phase 1 shows a problem), phrases, fingerprints, calibration.
2. Compare old and new `phrase_bank.json`: counts by mode, cadence class, beats, bytes. Put the table in `docs/FINAL_REPORT.md` under a new "Revision 2" heading.
3. Commit, then tag `handoff-0.2.3-r2` (or the folder-renamed tag) so Repo B's maintainer can pin an exact version in `assets/PROVENANCE.md`.
4. Tell the user which Repo B phases are now unblocked: seeds can proceed once the bank reports adequate per-mode counts; the fingerprint decision can use `docs/fingerprint_options.md`.

## 10. Risks

| Risk | Mitigation |
|---|---|
| New classifier mislabels differently (swaps one bias for another) | Hand-written unit cases; confusion matrix; 20-phrase human review table in the audit |
| Kurd pool is simply too small, so the bank still has few Kurd phrases | Shortfall is reported explicitly and never padded; Repo B falls back to `mode=any` |
| Quota for rare modes lowers overall diversity | Quota is small (default 4 per mode per class); remaining slots keep farthest-point selection |
| Hijaz, bayati and saba templates are rough approximations of maqam practice | Comment each approximation; keep fallback to `minor-like` when evidence is thin; ask the user to listen to a few labeled examples |
| Sketch variants weaken novelty detection | Re-calibrate per variant; document missed cases; keep the full variant available |
| Regenerated outputs break the Repo B plan's assumptions | Keep file names and field names; add fields only; bump `schema` string; record in `HANDOFF_REVISION.md` |

## 11. Order of work and stop points

1. Phase 1, then **stop and show the user `out/mode_audit.md`** (it decides how much of the Kurd shortage is data and how much is classifier).
2. Phases 2 and 3 together. Show the confusion matrix and the new `by_mode_hint` counts.
3. Phases 4 and 5 can run in parallel with 2 and 3.
4. Phase 6, then Phase 7.
5. Phase 8 last. Report which Repo B phases are unblocked.

Never edit the corpus zip, never overwrite old calibration files without keeping the previous numbers in the report, and never force-push.
