# abcsim maintenance plan: feeding `abc-score-writer` v0.2.3

**Audience:** the AI agent that maintains `abcsim`.
**Goal:** turn abcsim's similarity results into assets that make the `abc-score-writer` skill (v0.2.2) more accurate, without making the skill's agent slower.

## 0. Context and hard constraints

- The corpus is **670 Suno songs** (`suno-0000.abc` to `suno-0669.abc`), transcribed by SheetSage2. 644 have a usable vocal, 26 have an empty vocal, and 82 have `Ins` as lead voice (`out/validation.csv`).
- abcsim already shows that about **127 songs (19%) share long melodic segments** with another song (z ≥ 30 within the top-300 pair list). Suno variants are probably inflating the corpus percentiles.
- Two repositories are involved:
  - **Repo A, abcsim (yours).** May use `numpy`, `numba`, `matplotlib`, `mido`.
  - **Repo B, `abc_score_composer` (the skill, tag `v0.2.2`).** Rule: **standard library plus `abc2midi` only.** Never add a dependency to Repo B.
- **You never edit Repo B.** You produce a ready-to-copy folder `handoff/skill_0.2.3/` plus a report. A human decides what to adopt.
- **Footprint rule.** The skill's agent reads SKILL.md (about 5.8 KB) and writes a roughly 1.2 KB `fill.json`. Nothing you build may increase what the agent must read. All large assets are consumed by scripts, and the agent only ever sees a tiny printed summary (at most about 400 B).
- Do not recompute all-pairs alignment (about 10 min). Reuse `out/index.pkl` and `out/pairs_raw.npz`. `pairs_raw.npz` holds `pairs` (224115×2) and `res` (224115×5: raw score, `sA`, `eA`, `sB`, `eB`, all token indices).
- Keep everything cross-platform. The user is on Windows/PowerShell, so use `pathlib`, UTF-8, and no shell-only steps.
- Documentation is **Markdown**. Update `abcsim/README.md` for every new script.

## 1. Phase 1: shared z-score module

`run_report.py` computes z inline (regression of raw score on `log(nA*nB)`, robust MAD sigma). Several new scripts need the same z.

**Tasks**
1. Extract that logic into `abcsim/stats.py: compute_z(idx, pairs, res) -> np.ndarray`.
2. Make `run_report.py` import it. Output must stay **byte-identical** (`top_pairs.csv`, `groundtruth.txt`) on the existing `out/` data.

**Acceptance:** the diff of regenerated `top_pairs.csv` against the committed copy is empty.

## 2. Phase 2: near-duplicate clustering (`abcsim/cluster_dups.py`)

**Input:** `out/index.pkl`, `out/pairs_raw.npz`, optional `--z-min` (default to be calibrated), optional `--min-coverage`.
**Output:** `out/clusters.json`, `out/dedupe_keep.txt`, `out/dedupe_report.md`.

**Algorithm**
1. Compute z for every pair with `compute_z`.
2. An edge exists when z ≥ `--z-min` **and** the aligned segment covers at least `--min-coverage` of the shorter song's tokens (default 0.25). This avoids joining songs that merely share a chorus riff.
3. Cluster with union-find, but guard against chaining: if a cluster's diameter is large, split it with average-linkage and report the split.
4. Pick one representative per cluster by this priority:
   1. non-empty vocal and lead voice is `Vocal`;
   2. no flags in `validation.csv`;
   3. bar count nearest the corpus median (146);
   4. lowest song id as the tiebreak.
5. Songs in no cluster are kept as singletons.

**Calibrating `--z-min` (do not guess)**
- Sweep z-min over {15, 30, 50, 100, 200} and print clusters and songs affected for each.
- Use `export_segments.py` to write MIDI excerpts for 8 pairs near the chosen threshold, and record in the report what separates "same melody" from "same genre cliché". The user will listen to these.
- Seed ground truth: `duplicates_report.csv` already marks `suno-0432` / `suno-0620` as a 96.67% text duplicate. They must land in the same cluster at the chosen threshold. Add that as a test.

**Known limitation to handle:** only the lead voice is compared, so cross-lead duplicates (Ins-lead vs Vocal-lead songs) can be missed. Add `--voice vocal` to `build_index.py` and `run_similarity.py` (see Phase 4) and note in the report which clusters were found only in vocal mode.

**Acceptance**
- Clusters are reproducible (same input gives same output).
- Report lists: cluster count, songs removed, the `suno-0432`/`suno-0620` check, and the top 10 largest clusters.

## 3. Phase 3: does deduping change the skill's bands?

Do **not** re-implement the skill's statistics. Call Repo B's `scripts/mine_corpus.py` as a black box.

**Tasks**
1. `abcsim/export_dedup_corpus.py`: copy the kept files (from `dedupe_keep.txt`) into `out/corpus_dedup/`. The original files stay untouched.
2. Run, using a local checkout of Repo B at tag `v0.2.2`:
   ```
   python <repoB>/scripts/mine_corpus.py --corpus <full_corpus_dir>  --out out/profile_full.json
   python <repoB>/scripts/mine_corpus.py --corpus out/corpus_dedup   --out out/profile_dedup.json
   ```
   If the full-corpus run does not reproduce Repo B's committed `assets/corpus_profile.json`, stop and report the mismatch before continuing.
3. `abcsim/compare_bands.py` writes `out/bands_shift.md`: a table of p10/p25/p50/p75/p90 for every metric, full vs deduped, plus a "shift as % of IQR" column. Highlight any metric shifting by more than **10% of its IQR**. Include the forms table (top section orders), chord-change ranks, and key distribution.

**Acceptance:** `bands_shift.md` exists and states a recommendation: adopt the deduped profile, or keep the current one because shifts are immaterial. Put the deduped `corpus_profile.json` in `handoff/skill_0.2.3/assets/` as a **candidate**, labelled as such.

## 4. Phase 4: vocal-only index (prerequisite for the phrase bank)

- Add `--voice {lead,vocal,ins}` to `build_index.py` (default `lead`, so existing behavior is unchanged). Cache to a separate file such as `out/index_vocal.pkl`.
- `features.song_stream` already accepts `voice=`. Reuse it.
- Songs with an empty vocal (26) are skipped and counted in the log.
- Phase 2's vocal-mode clustering reuses this index. Running all-pairs on about 644 vocal streams takes roughly 10 minutes on one core; run it once and cache.

**Acceptance:** with `--voice lead`, the existing outputs reproduce exactly.

## 5. Phase 5: phrase bank (`abcsim/export_phrases.py`)

**Purpose:** a small bank of real vocal phrases, in the skill's own grammar, that the skill's intake step can offer as optional seeds.

**Read first (in Repo B):** `scripts/abc_common.py: degree_to_midi`, `spell_midi`, and `references/blueprint_schema.md`. Match its **octave convention and degree spelling exactly**. Degrees: `1,b2,2,b3,3,4,b5,5,b6,6,b7,7` (and `#4`), trailing `+`/`-` for octaves, durations in quarter-note beats, trailing `~` for ties, `r:<beats>` for timed rests.

**Steps**
1. Use only the **deduped** set (Phase 2) and songs with a `Vocal` voice.
2. Read the tonic from `K:` and convert each note to a degree. Semitone 6 maps to `b5`. Notes outside the grammar must not appear; if a phrase needs one, drop the phrase.
3. Segment into phrases at rests of at least 1 beat or at bar boundaries. Keep phrases of **16 beats** (a shatr, 4 bars of 4/4) and **8 beats** (a short line). Normalize 2/4 songs by beat count, not bar count.
4. Quality filters: at least 5 distinct pitches, `repeated_note_ratio` below 0.5, span within 12 semitones, no `Z`/multi-bar rests inside, no out-of-grid durations, and the corpus's off-meter 1/4 slips excluded.
5. Index each phrase by: `beats`, `end_degree`, `cadence_class` (matching the skill's rules: sadr ends on 2/4/5; ajuz ends on 5, or 1 only at a section end), `mode_hint` (key's maqam-like flavor, e.g. Kurd-like if `b2`,`b3`,`b6`,`b7` dominate), `source_id`, `source_bars`, and `register` (low, mid, high).
6. **Role labels are heuristic.** The corpus has no lyrics, so sadr/ajuz is inferred only from cadence and position. Label the field `role_hint`, never `role`.
7. Select a diverse subset with a greedy farthest-point pick over token distance (reuse `sw_pair` or a simple interval-histogram distance). Target **20-40 phrases per cadence class**, at most one per cluster, at most 3 from the same source song.
8. Write `handoff/skill_0.2.3/assets/phrase_bank.json`. Budget: at most 60 KB; the file is read by scripts, not by the agent.

**Round-trip test (mandatory):** for every phrase, convert degrees back to pitches with Repo B's `degree_to_midi` and compare against the source notes after tonic and octave normalization. Count of mismatches must be **0**. This test imports Repo B only for testing.

**Acceptance:** `phrase_bank.json` validates, round-trip passes, and a printed summary shows counts per cadence class and per register.

## 6. Phase 6: novelty fingerprints for a release-time check

**Purpose:** let the skill warn when a composed melody is too close to a corpus melody. Repo B cannot use numpy, so build the fingerprint here and a stdlib reader for Repo B.

**Fingerprint definition.** Use abcsim's own tokens: `interval` clipped to ±12 and `rc = round(2*log2(IOI ratio))` clipped to ±4 (see `features.tokens_from_notes`). Form 8-token n-grams, hash each to 32 bits, and store the sorted unique hashes per **representative** song (Phase 2), from its vocal stream.

**Deliverables**
1. `abcsim/export_fingerprints.py` writes `handoff/skill_0.2.3/assets/corpus_fingerprints.bin` plus a small JSON header (n, hash function, song ids). Size budget: **at most 1 MB**. If over budget, fall back to a bottom-k sketch per song and document the accuracy loss.
2. `handoff/skill_0.2.3/scripts/novelty_check.py`: **stdlib only.** It reads the compiled `song.abc` using Repo B's own parser (it will live in Repo B's `scripts/` beside `abc_common.py`), builds the same tokens, and prints at most one line: the closest corpus song, containment (share of the composition's n-grams found in that song) and matched beats. Advisory only, in the same spirit as CRAFT flags.
3. **Token parity test:** on all 670 songs, the stdlib tokenizer in `novelty_check.py` must produce the **identical** token stream as the numpy version (`features.py`). Any difference is a bug in the port.

**Calibration**
- Positives: pairs from the clusters in Phase 2 should score high.
- Negatives: sample random unrelated pairs; none may exceed the proposed threshold.
- Also test a **fresh composition**: run `assets/example_song.abc` from Repo B. Record its result. Pick the threshold so unrelated pairs and the example song stay below it. Write the chosen value and its false-positive rate in `docs/novelty_calibration.md`.

**Acceptance:** parity test passes on 670/670, calibration doc exists, and the check runs in under 1 second on a 30-bar score.

## 7. Phase 7: handoff package and report

Create `handoff/skill_0.2.3/` containing only:

```
assets/phrase_bank.json
assets/corpus_fingerprints.bin
assets/corpus_profile.dedup.candidate.json   (only if Phase 3 recommends it)
scripts/novelty_check.py
CHANGELOG_SNIPPET.md      (proposed text for 0.2.3, including footprint numbers)
INTEGRATION.md            (exactly where Repo B's intake/inspect would call each asset)
```

`INTEGRATION.md` must say: intake may print 2-3 phrase matches (about 400 B max) as optional seeds; `validate_and_inspect.py` may call `novelty_check.py` and print one advisory line; mandatory reading must not grow. Report measured footprint before and after.

Also write `docs/FINAL_REPORT.md` with: cluster results, band shifts, phrase-bank statistics, novelty calibration, and an honest list of limitations.

## 8. Tests and checks (add under `tests/`)

- `test_stats_parity`: Phase 1 refactor reproduces old z outputs.
- `test_clusters_seed`: `suno-0432` and `suno-0620` share a cluster.
- `test_roundtrip_phrases`: zero mismatches (skipped if Repo B is not checked out).
- `test_token_parity`: stdlib and numpy tokens are identical on all songs.
- `test_assets_size`: phrase bank ≤ 60 KB, fingerprints ≤ 1 MB.

## 9. Known risks

| Risk | Mitigation |
|---|---|
| z threshold merges stylistically similar but different songs | Coverage rule, calibration sweep, listening excerpts, human sign-off |
| Lead-voice-only similarity misses duplicates | Vocal-only index (Phase 4) |
| `role_hint` mistaken for ground truth | Named `role_hint`; documented as inferred |
| Phrase bank steers the agent toward one maqam | Report counts by `mode_hint`; cap per source and per cluster |
| Tokens drift between numpy and stdlib versions | Parity test on all 670 songs |
| Corpus ratings (4-5 stars) are not recorded in the files | Do not claim a rating filter; ask the user for a list if they want one applied |

## 10. Order of work and stop points

1. Phase 1, then Phase 2. **Stop and show the user** the cluster report and the listening excerpts.
2. Phase 3. **Stop** for the user's decision on adopting the deduped profile.
3. Phase 4, 5 and 6 can run once Phase 2 is approved.
4. Phase 7 last.

Never delete or overwrite `out/index.pkl`, `out/pairs_raw.npz`, or the original corpus zip.
