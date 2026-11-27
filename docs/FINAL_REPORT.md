# abcsim maintenance report: assets for abc-score-writer 0.2.3

**Status:** Phases 1-7 implemented; **Revision 2 (`handoff-0.2.3-r2`)** fixes F1-F10.
Phase 2 and Phase 3 stop points were reviewed; Phase 2 listening confirmed all
8 above-cut pairs as the same melody and exposed one weighted-alignment false
negative, which is now handled by a narrow rescue pass. Repo B was not modified;
the deliverable is `handoff/skill_0.2.3/`.

## 1. Shared z-score module (Phase 1)

- `abcsim/stats.py` now holds `compute_z(idx, pairs, res)` and `null_model`.
- `run_report.py` imports it; the regenerated `out/top_pairs.csv` and
  `out/groundtruth.txt` are **byte-identical** to the committed copies.
- One line-ending fix was needed: `csv.DictWriter` now writes `\n` explicitly,
  matching the committed LF files on all platforms.
- `tests/test_stats_parity.py` compares against a literal copy of the old
  formula and against the committed `top_pairs.csv` z column.

## 2. Near-duplicate clusters (Phase 2)

Chosen cut: **z >= 50**, **coverage >= 0.25** of the shorter song. The z
distribution has a gap (duplicate block z >= 60, shared-riff block z <= 35); a
sweep at 15/30/50/100/200 is in `out/dedupe_report.md`.

| metric | value |
|---|---|
| clusters | 54 |
| songs in clusters | 125 |
| songs removed | 71 |
| songs kept | 599 |
| weighted main-rule edges | 88 |
| rescue-pass edges | 2 |
| cluster sizes | 39 pairs, 13 triples, 2 quadruples |
| seed check | `suno-0432` / `suno-0620` together in C053: PASS |

**Rescue pass.** Listening showed `suno-0089` / `suno-0108` (weighted z=30.7,
coverage 0.08) is the same melody, but the rarity-weighted local alignment
stops early on rhythmic variants. A second pass runs an unweighted local
alignment and accepts only if it covers >= 50% of the shorter song **and** a
whole-song global alignment scores >= 0. That admits:

- `suno-0089` / `suno-0108` (uniform coverage 0.958, global +3), confirmed by
  listening;
- `suno-0106` / `suno-0122` (uniform coverage 0.979, global +92), the strongest
  automatic rescue.

The two below-cut controls from the listening sheet scored global -523 and
-353, so they are rejected. The chaining guard found no non-clique clusters.
Outputs: `out/clusters.json`, `out/dedupe_keep.txt`, `out/dedupe_report.md`,
`out/listen_pairs.tsv`, `out/rescue_pairs.tsv`, plus MIDI excerpts in
`out/listen/`.

## 3. Deduped-corpus band comparison (Phase 3)

Repo B `v0.2.2` was checked out locally. Running its `scripts/mine_corpus.py`
on the full 670-file corpus reproduced the committed
`assets/corpus_profile.json` **exactly**. The deduped run used the 599 kept
files.

| | full | deduped |
|---|---|---|
| files | 670 | 599 |
| used for vocal stats | 644 | 596 |
| empty vocal | 26 | 3 |

**Recommendation: keep the current profile.** The largest percentile shift is
**3.6% of the full-corpus IQR** (`ins_active_bars`), below the 10% threshold.
Forms, chord-quality/loop ranks, and key distribution are essentially
unchanged; counts drop because duplicate files are removed. Full table:
`out/bands_shift.md`.

The deduped profile is included as a **candidate**, not adopted:
`handoff/skill_0.2.3/assets/corpus_profile.dedup.candidate.json`.

## 4. Vocal-only index (Phase 4)

`build_index.py` and `run_similarity.py` gained
`--voice {lead,vocal,ins}`. The lead default keeps the old paths; the vocal
run writes `out/index_vocal.pkl` and `out/pairs_raw_vocal.npz`.

- Vocal index: **644 songs**, **26 skipped** (no usable Vocal).
- Vocal all-pairs (207,046 pairs) was run once and cached as
  `out/pairs_raw_vocal.npz`; Phase 2 was repeated into `out/vocal/`.
- Vocal clustering: **44 clusters, 92 songs, 48 removed, 596 kept**; seed
  `0432/0620` passes in C043; 2 rescue edges.
- Pair comparison (`out/vocal/clusters_lead_vs_vocal.md`): 52 vocal pairs,
  90 lead pairs, **50 shared**, **2 vocal-only**, 40 lead-only.
- **Vocal-only pairs** (missed by the lead run):
  - `suno-0105` / `suno-0167` (vocal z=170.3, coverage 0.899), cluster C020.
  - `suno-0381` / `suno-0648` (vocal z=189.1, coverage 0.985), cluster C042.
- **Clusters found only in vocal mode:** C020 and C042. These are candidates
  for human review, not automatic merges.
- Most lead-only pairs are expected: 82 songs use `Ins` as lead, so the vocal
  index either skips them or compares a different melodic line.

## 5. Phrase bank (Phase 5)

`handoff/skill_0.2.3/assets/phrase_bank.json` — **48 phrases**, 32,853 bytes.

| dimension | counts |
|---|---|
| cadence class | sadr 24, ajuz 24 |
| length | 8 beats 35, 16 beats 13 |
| register | mid 24, high 24 |
| mode hint | nahawand-like 39, rast-like 4, major-like 2, saba-like 1, kurd-like 1, bayati-like 1 |

Generated from 21,396 candidate phrases in the deduped set, using only Vocal
streams. Selection is greedy farthest-point over interval + duration
histograms, at most one phrase per Phase 2 cluster and at most three per source
song. Degrees use Repo B's convention (`1` = tonic in octave 4, trailing
`+`/`-` octaves, semitone 6 = `b5`). `role_hint` is inferred from cadence and
length only; it is never called `role`.

**Round-trip:** 48/48 phrases convert back through Repo B's
`abc_common.degree_to_midi` to the exact source MIDI notes; 0 mismatches
(`tests/test_phrases.py`). The bank is mode-biased toward nahawand-like, which
reflects the corpus and is reported as a limitation.

## 6. Novelty fingerprints (Phase 6)

`handoff/skill_0.2.3/assets/corpus_fingerprints.bin` — 596 deduped
representatives, **249,371** 8-gram hashes, **1,027,894 bytes** (under 1 MB, no
sketch needed).

`handoff/skill_0.2.3/scripts/novelty_check.py` is stdlib-only and reads
Repo B's parser. It prints at most one advisory line. Token parity with
`features.tokens_from_notes` passes on **670/670** songs; Repo B's parser
differs on double accidentals and mid-song key changes, so the checker
pre-normalizes pitches to abcsim's dialect while still using Repo B for bars,
durations, ties, and onsets.

Calibration (`docs/novelty_calibration.md`):

| | value |
|---|---|
| threshold | containment >= **0.05** |
| within-cluster positives | 47 pairs, median 0.463, 46/47 >= threshold |
| random negatives | 2,968 pairs, max 0.0165, **0 false positives** |
| Repo B example song | containment 0.000, status ok |
| runtime | ~0.3 s on a 30-bar score |

## 7. Handoff and footprint (Phase 7)

`handoff/skill_0.2.3/` contains only:

```
assets/phrase_bank.json
assets/corpus_fingerprints.bin
assets/corpus_profile.dedup.candidate.json
scripts/novelty_check.py
CHANGELOG_SNIPPET.md
INTEGRATION.md
```

Measured with Repo B `scripts/measure_footprint.py` before and after applying
the handoff to a copy: **SKILL.md 5,824 B** and **mandatory reading 26,484 B**
are unchanged; example fill stays 1,241 B; inspector output stays 11/20 words.
The new optional output is <= 400 B of phrase seeds and <= 120 B for the
novelty line. Assets are read by scripts, not by the agent.

## 8. Tests

```
python -m pytest tests -q
```

Covered: stats parity, seed clustering, reproducibility, rescue pairs,
phrase round-trip, source-note existence, stdlib/numpy token parity on all 670,
novelty example/self-containment, asset size and phrase schema.

## 9. Limitations

- **Lead-voice default.** Cross-lead duplicates (Ins-lead vs Vocal-lead) can be
  missed by the lead run; the vocal run addresses this but skips 26 songs with
  no Vocal. Do not merge the two runs automatically.
- **Rescue is narrow by design.** It catches rhythmic variants with a long
  unweighted alignment and a non-negative global score; it can still miss
  variants with large structural differences.
- **Role is inferred.** The corpus has no lyrics; `role_hint` comes from
  cadence and length only. `sadr_or_ajuz` is deliberately ambiguous for
  phrases ending on 5.
- **Phrase modes are imbalanced.** 39/48 are nahawand-like. Counts are
  reported; selection caps only per cluster/source, as the plan specifies.
- **Fingerprints are exact 8-grams.** A rhythmically varied variant can score
  low (one counted cluster pair is below 0.05); the check is advisory, not a
  plagiarism verdict.
- **No rating filter.** Corpus ratings are not recorded in the files, so none
  was applied.
- **12-TET.** Maqam quarter-tones are already lost in the ABC transcriptions.

## 10. Reproduce

```bash
python abcsim/run_report.py out
python abcsim/cluster_dups.py out
python abcsim/export_dedup_corpus.py CORPUS out
python <repoB>/scripts/mine_corpus.py --corpus CORPUS --out out/profile_full.json
python <repoB>/scripts/mine_corpus.py --corpus out/corpus_dedup --out out/profile_dedup.json
python abcsim/compare_bands.py out
python abcsim/build_index.py CORPUS --voice vocal --cache out/index_vocal.pkl
python abcsim/run_similarity.py CORPUS out --voice vocal
python abcsim/cluster_dups.py out/vocal --index out/index_vocal.pkl \
    --pairs out/pairs_raw_vocal.npz --validation out/validation.csv
python abcsim/compare_cluster_runs.py out
python abcsim/export_phrases.py CORPUS out --max-phrase-bytes 130
python abcsim/export_fingerprints.py CORPUS out --sketch-k 256 --threshold 0.08
python abcsim/calibrate_novelty.py CORPUS out
python -m pytest tests -q
```

## 11. Revision 2 (`handoff-0.2.3-r2`)

Revision 2 addresses integration issues F1–F10 identified against commit `9480245`
(see `ABCSIM_FOLLOWUP_PLAN.md` and `handoff/skill_0.2.3/HANDOFF_REVISION.md`).

- **Mode audit & classifier (F1, F4):** `abcsim/audit_modes.py` measured 2,249 of
  21,396 candidates (10.5%) containing `b2`. `export_phrases.py` replaced the
  small-scale-penalizing share rule with full scale-tone `MAQAM_TEMPLATES`,
  a two-stage distinguishing-degree rule, and minimum-evidence guards
  (`MIN_MODE_NOTES = 6`, `MIN_MODE_SHARE = 0.70`), changing 4,232 of 21,396
  labels (19.8%; old `P010` `saba-like` -> `kurd-like`).
- **Mode quotas & seed byte budget (F2, F3, F5):** `--min-per-mode 4` and
  `--max-phrase-bytes 130` (`schema: "phrase_bank/2"`, `phrase_bytes`,
  `fits_seed_budget`, `counts.mode_shortfall`) raise rare-mode coverage and keep
  all 48 selected phrases within 130 B. Only 3 of 48 phrases are 16-beat, so
  `INTEGRATION.md` recommends 8-beat seeds.
- **Fingerprint size control (F8):** Added `--budget-bytes`, `--sketch-k`, and
  sketch support in `novelty_check.py` and `calibrate_novelty.py`. Default
  `corpus_fingerprints.bin` switched to `bottom-256` (630,382 B @ `0.08`), with
  `full`, `k512`, `k128`, and `k64` variants in `handoff/skill_0.2.3/assets/alt/`
  and calibrated in `docs/fingerprint_options.md`.
- **Portability & handoff docs (F6, F7, F9, F10):** Replaced hardcoded `/tmp/`
  paths with `abcsim/repo_b.py`; removed the source key from the `SEED` example
  and stated tonic-relative degrees; removed hardcoded 0.2.2 footprint baselines;
  restricted compact-card novelty output to `status=close`; added an honest
  limitations section and `handoff/skill_0.2.3/HANDOFF_REVISION.md`.

### Old (`9480245`) vs. Revision 2 (`handoff-0.2.3-r2`)

| metric | `9480245` (r1) | Revision 2 (r2) |
|---|---|---|
| `phrase_bank.json` schema / size | `phrase_bank/1` (implicit) / 32,853 B | `phrase_bank/2` / 34,788 B |
| phrases (`sadr` / `ajuz`) | 48 (24 / 24) | 48 (24 / 24) |
| beats (`8` / `16`) | 35 / 13 | 45 / 3 |
| phrase bytes (min / med / max) | 29 / 105 / 275 B | 29 / 94 / 129 B (48/48 <= 130 B) |
| `by_mode_hint` | nahawand 39, rast 4, major 2, kurd 1, bayati 1, saba 1 | nahawand 15, kurd 8, hijaz 8, rast 8, minor 6, major 2, bayati 1 |
| `counts.mode_shortfall` | not reported | `bayati-like`: wanted 8 (4/4), got 1 (1 sadr, 0 ajuz) |
| default `corpus_fingerprints.bin` | full set (1,027,894 B, 249,371 hashes) | `bottom-256` (630,382 B, 150,037 hashes) |
| threshold / positives caught | `0.05` / 46 of 47 | `0.08` / 45 of 47 |
| unrelated max / FP | pair max `0.0165`, 0 FP | pair max `0.0199` (0 FP), whole-bank max `0.0640` (0 FP; excludes vocal `C020`/`C042`) |
