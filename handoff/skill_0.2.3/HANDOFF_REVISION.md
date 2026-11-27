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
