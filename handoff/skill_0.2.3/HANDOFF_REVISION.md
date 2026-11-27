# Handoff Revision 3 (`handoff-0.2.3-r3`)

**Pin this tag (or later).** `handoff-0.2.3-r2` ships a broken `novelty_check.py`; do not integrate it.

- **Base:** tag `handoff-0.2.3-r2` (commit `fcbf23a`).
- **Target revision:** Revision 3 (`handoff-0.2.3-r3`). One defect fixed; no change to any asset (`phrase_bank.json`, every `.bin` fingerprint bank and its stamped threshold are byte-identical to r2).
- **Layout:** unchanged. File names under `handoff/skill_0.2.3/` are preserved.

## The bug in r2

`novelty_check.check()` passed the raw `(hash, position)` list from `composition_grams()` straight to `match_song()`, which expects `prepare(grams)` output (`{hash: [positions]}`); `best_match()` did it correctly. Result:

| Bank | r2 behaviour |
|---|---|
| default (`bottom-256`), `k512`, `k128`, `k64` | `TypeError: '<=' not supported between instances of 'tuple' and 'int'` |
| `full` | **silent false negative**: `closest=none containment=0.000 status=ok` even for an unmodified corpus song (a tuple is never `in` a set of ints) |

`check()` also treated the matched hashes returned by `match_song()` as positions when computing `matched_beats`. The regression came with the sketch-estimator refactor; the suite missed it because calibration and tests only exercised `prepare()` + `match_song()` / `best_match()`, never `check()` on a real song.

## What changed

1. **`scripts/novelty_check.py`**
   - `check()` now goes through `best_match()`: there is one ranking loop, shared by the CLI, the skill, the tests and the calibration. Matched beats are computed from the matched hashes' positions (`matched_positions(prep, matched)`), with `beats_tiebreak(notes, prep)` as the tie-breaker among equal containment.
   - `match_song()`, `best_match()` and `matched_positions()` accept either `prepare()` output or a raw `[(hash, position)]` list (normalised by `_prepared()`; anything else raises `TypeError`), so this input-shape mix-up cannot recur. Return values are unchanged: `match_song` returns `(matched_hashes, denominator)` with the denominator the number of **distinct** hashes (at or below `tau` for a sketch).
   - Definitions are unchanged: each distinct 8-gram counts once; sketches use the bottom-k estimator with `MIN_SKETCH_MATCHES = 3`.
2. **`tests/test_novelty.py`** (+ new end-to-end tests, all calling `check()`): positive control (whole corpus song and a half-song vocal excerpt, `status=close`) on all five banks; negative control (Repo B `example_song.abc`, `status=ok`) on all five banks; no exceptions on any bank; `check()` vs `best_match()` parity on the sketch banks; each bank's stamped threshold applied when `--threshold` is not given (0.08 default / `full` / `k512`, 0.15 `k128` / `k64`), tested with an input scoring about 0.1 so the wrong threshold changes the status; the CLI prints exactly what `check()` returns; the script works as deployed beside `abc_common.py`. Without a Repo B checkout the positive controls still run (the two parsing hooks are pointed at abcsim's parser; everything after parsing is the real `check()`); the Repo B example, CLI and deployment tests skip.
3. **`abcsim/calibrate_novelty.py`**: the Repo B example is now scored through `check()`, and every positive member is also run end-to-end through `check()` and compared with the estimator (new "End-to-end check through `check()`" tables in `docs/novelty_calibration.md` and `docs/fingerprint_options.md`). The "previous numbers" section no longer reads a file that every default run overwrites.

## Calibration reconfirmed through the fixed `check()` path

Run with `ABC_SCORE_COMPOSER` set. **All figures and all recommended thresholds are unchanged**, so no threshold was recomputed.

| Bank | stamped threshold | positives flagged `close` by `check()` (of 47) | `check()` agrees with the estimator on the representative | Repo B example |
|---|---|---|---|---|
| `bottom-256` (default) | 0.08 | 45 | 46 / 46 | `0.000`, `status=ok` |
| `full` | 0.08 | 45 | 47 / 47 | `0.000`, `status=ok` |
| `k512` | 0.08 | 45 | 47 / 47 | `0.000`, `status=ok` |
| `k128` | 0.15 | 43 | 46 / 46 | `0.000`, `status=ok` |
| `k64` | 0.15 | 43 | 46 / 46 | `0.000`, `status=ok` |

- Default bank: 45 of 47 positives, unrelated-pair max `0.0199` (0 FP), whole-bank unrelated max `0.0640` / p99 `0.0414` (0 FP) are reproduced exactly. The calibration's own estimator calls were already on the correct `prepare()` path, which is why the numbers hold; what was missing was proof that `check()` agrees with it, and that proof is now part of the calibration output and the test suite.
- Positive control on `suno-0100.abc` (an unmodified corpus song): `closest=suno-0100.abc containment=1.000 status=close` on all five banks (r2: crash on four banks, `closest=none status=ok` on `full`).

---

# Handoff Revision 2 (`handoff-0.2.3-r2`)

- **Base commit (initial 0.2.3 handoff):** `9480245` ("Add project README")
- **Target revision:** Revision 2 (`handoff-0.2.3-r2`), fixing issues F1–F10 found during `abc_score_composer` (Repo B) integration planning.
- **Layout:** File names under `handoff/skill_0.2.3/` are preserved; alternative fingerprint files live under `handoff/skill_0.2.3/assets/alt/`.

## Summary of changes from commit `9480245`

1. **Maqam classifier (`abcsim/export_phrases.py`, `abcsim/audit_modes.py`):**
   Replaced the small-scale-penalizing template share rule with full scale-tone templates (`MAQAM_TEMPLATES` with `core`, `tolerated`, `branch`, `requires_all`, `requires_any`) and a two-stage rule with minimum-evidence guards (`MIN_MODE_NOTES = 6`, `MIN_MODE_SHARE = 0.70`), falling back to `minor-like` / `major-like` when ambiguous. Across 21,396 candidates, 4,232 (19.8%) changed label; `P010` from the 0.2.3 bank reclassified from `saba-like` to `kurd-like`.
2. **Mode quotas (`abcsim/export_phrases.py`):**
   Added `--min-per-mode` (default `4` per cadence class) and `--modes` targeting Repo B's intake modes, plus explicit shortfall reporting under `counts.mode_shortfall` (no silent padding).
3. **Seed byte budget & schema 2 (`phrase_bank.json`):**
   Added `phrase_bytes`, `fits_seed_budget` (`<= 130` B), `--max-phrase-bytes 130`, `schema: "phrase_bank/2"`, and `generated_from.selection` metadata. Recommended 8-beat seeds in `INTEGRATION.md` because 45 of 48 selected phrases are 8-beat.
4. **Fingerprint size control & sketch estimator (`corpus_fingerprints.bin`, `novelty_check.py`, `export_fingerprints.py`, `calibrate_novelty.py`):**
   Added `--budget-bytes` and `--sketch-k`, made `novelty_check.py` sketch-aware (`tau`, `MIN_SKETCH_MATCHES = 3`, header `threshold`), switched the default bank to `bottom-256` (630,382 B @ `0.08`), and placed `full`, `k512`, `k128`, `k64` under `assets/alt/`.
5. **Portability & documentation (`abcsim/repo_b.py`, `INTEGRATION.md`, `CHANGELOG_SNIPPET.md`):**
   Removed all `/tmp/...` path defaults via `repo_b.find_repo_b()` (`ABC_SCORE_COMPOSER`, sibling, home), removed the source key from the `SEED` example and stated tonic-relative degrees, replaced hardcoded 0.2.2 footprint figures with instructions to re-measure on the target commit (noting the `5,824 B` vs `5,808 B` discrepancy), restricted compact-card novelty printing to `status=close`, and added an honest limitations section.

## Before / After (`9480245` vs. Revision 2)

| Artifact / Metric | Base (`9480245`) | Revision 2 (`handoff-0.2.3-r2`) |
|---|---|---|
| `phrase_bank.json` schema | `phrase_bank/1` (implicit) | `phrase_bank/2` (`phrase_bytes`, `fits_seed_budget`, `selection`) |
| `phrase_bank.json` size | 32,853 B | 34,788 B |
| Phrases (sadr / ajuz) | 48 (24 / 24) | 48 (24 / 24) |
| Beats (8 / 16) | 35 / 13 | 45 / 3 |
| Phrase byte length (min / med / max) | 29 / 105 / 275 B | 29 / 94 / 129 B (48/48 <= 130 B) |
| Mode distribution (`by_mode_hint`) | nahawand 39, rast 4, major 2, kurd 1, bayati 1, saba 1 | nahawand 15, kurd 8, hijaz 8, rast 8, minor 6, major 2, bayati 1 |
| Mode shortfall (`counts.mode_shortfall`) | not reported | `bayati-like`: wanted 8 (4/4), got 1 (1 sadr, 0 ajuz) |
| Register (mid / high / low) | 24 / 24 / 0 | 16 / 29 / 3 |
| Default `corpus_fingerprints.bin` | full set (1,027,894 B, 249,371 hashes) | `bottom-256` sketch (630,382 B, 150,037 hashes) |
| Alt fingerprint variants (`assets/alt/`) | none | `full` (1,027,911 B @0.08), `k512` (984,499 B @0.08), `k128` (334,812 B @0.15), `k64` (181,817 B @0.15) |
| Novelty advisory threshold | `0.05` (hardcoded) | `0.08` (stamped in header; `0.15` for `k128`/`k64`) |
| Calibration positives caught | 46 / 47 (`>= 0.05`, set-based) | 45 / 47 (`>= 0.08`, runtime estimator on `bottom-256`) |
| Calibration unrelated max / FP | pair max `0.0165`, 0 FP (whole-bank not run) | pair max `0.0199` (0 FP), whole-bank max `0.0640` / p99 `0.0414` (0 FP; excludes vocal clusters `C020` & `C042`) |
| Repo B example check | `0.000` (`status=ok`, ran locally) | not scored in CI without `ABC_SCORE_COMPOSER` |
| Compact-card novelty output | printed always (<= 120 B) | printed only on `status=close` (always in verbose mode) |
