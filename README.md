# abcsim

Melodic similarity and corpus-maintenance tools for SheetSage2 Arabic ABC
scores, plus the generated assets for
[`abc-score-writer`](https://github.com/akbargherbal/abc_score_composer)
`v0.2.3`.

The repository answers three questions:

1. **Which songs are near-duplicates?** — calibrated Smith-Waterman alignment
   on transposition/tempo-invariant tokens, with a residual-z null model,
   coverage filtering, and a narrow rescue pass for rhythmic variants.
2. **Does deduping change the skill's bands?** — Repo B's
   `scripts/mine_corpus.py` is run as a black box on the full and deduped
   corpora, then compared percentile-by-percentile.
3. **What can the skill reuse?** — a small bank of real vocal phrases in Repo
   B's `degree:beats` grammar and a stdlib-only novelty fingerprint check.

Repo B is **never modified** by this repository. Everything for the skill is a
ready-to-copy handoff in `handoff/skill_0.2.3/`; a human decides what to adopt.

## Install

```bash
pip install -r requirements.txt      # numpy, numba, matplotlib, mido
```

Python 3.10+ is recommended. Only abcsim uses numpy/numba/matplotlib/mido;
the handoff `novelty_check.py` is standard library only.

## Corpus

The repository includes the 670-song corpus as
`670_arabic_songs_abc_scores.zip`:

```bash
python -c "import zipfile; zipfile.ZipFile('670_arabic_songs_abc_scores.zip').extractall('.')"
export CORPUS=670_arabic_songs_abc_scores       # PowerShell: $env:CORPUS="670_arabic_songs_abc_scores"
```

`out/index.pkl` and `out/pairs_raw.npz` are the cached lead-voice all-pairs
result (224,115 pairs). Deleting them forces a ~10 minute recompute.

## Quick start: similarity and duplicates

```bash
python abcsim/run_validate.py   "$CORPUS" out     # out/validation.csv
python abcsim/run_similarity.py "$CORPUS" out     # ~10 min, 224k pairs
python abcsim/run_report.py     out               # top_pairs.csv, groundtruth.txt
python abcsim/cluster_dups.py   out               # clusters + dedupe_keep.txt
```

`cluster_dups.py` writes:

- `out/clusters.json` — clusters, representatives, rescue pairs
- `out/dedupe_keep.txt` — one representative per cluster + every singleton
- `out/dedupe_report.md` — calibration sweep, seed check, top clusters
- `out/listen_pairs.tsv`, `out/rescue_pairs.tsv` — listening pairs

The seed check is `suno-0432` / `suno-0620`; they must share a cluster.

### Listening excerpts

```bash
python abcsim/export_segments.py "$CORPUS" out --pairs out/listen_pairs.tsv --tag cal
python abcsim/export_segments.py "$CORPUS" out --pairs out/rescue_pairs.tsv --tag rescue
```

Each MIDI is: passage A, ~2 s silence, passage B (transposed/stretched to A).
Human sign-off is required before deleting any corpus file.

## Deduped corpus and band comparison

Requires a local checkout of Repo B at `v0.2.2`:

```bash
export REPO_B=/path/to/abc_score_composer

python abcsim/export_dedup_corpus.py "$CORPUS" out
python "$REPO_B/scripts/mine_corpus.py" --corpus "$CORPUS" --out out/profile_full.json
python "$REPO_B/scripts/mine_corpus.py" --corpus out/corpus_dedup --out out/profile_dedup.json
python abcsim/compare_bands.py out
```

`compare_bands.py` writes `out/bands_shift.md`. The full-corpus run must
reproduce Repo B's committed `assets/corpus_profile.json` (it does on
`v0.2.2`). The deduped profile is copied to the handoff as a **candidate**,
not adopted.

## Vocal-only index

```bash
python abcsim/build_index.py "$CORPUS" --voice vocal --cache out/index_vocal.pkl
python abcsim/run_similarity.py "$CORPUS" out --voice vocal
python abcsim/cluster_dups.py out/vocal --index out/index_vocal.pkl \
    --pairs out/pairs_raw_vocal.npz --validation out/validation.csv
python abcsim/compare_cluster_runs.py out
```

`--voice lead` is the default and keeps the old cache/output paths. The vocal
run skips songs without a usable Vocal and reports vocal-only clusters in
`out/vocal/clusters_lead_vs_vocal.md`.

## Phrase bank

```bash
python abcsim/export_phrases.py "$CORPUS" out
```

Writes `handoff/skill_0.2.3/assets/phrase_bank.json` (48 phrases, ~33 KB) using
only the deduped set and Vocal streams. Degrees follow Repo B's convention:

- `1` is the tonic in octave 4; trailing `+`/`-` shift octaves.
- Semitone 6 is spelled `b5`.
- Durations are quarter-note beats; `r:<beats>` is a timed rest.
- Roles are `role_hint` (inferred from cadence/length), never ground truth.

The mandatory round-trip test converts every phrase back through Repo B's
`abc_common.degree_to_midi`; it must have zero mismatches.

## Novelty fingerprints

```bash
python abcsim/export_fingerprints.py "$CORPUS" out
python abcsim/calibrate_novelty.py "$CORPUS" out
```

Writes:

- `handoff/skill_0.2.3/assets/corpus_fingerprints.bin` (8-token n-grams,
  sorted unique 32-bit hashes per representative)
- `docs/novelty_calibration.md`

The stdlib checker is
`handoff/skill_0.2.3/scripts/novelty_check.py`; copy it beside Repo B's
`abc_common.py`. It prints one advisory line:

```
NOVELTY closest=suno-0123.abc containment=0.123 matched=8.4 beats status=ok
```

Token parity with `features.tokens_from_notes` is tested on all 670 songs.

## Handoff for abc-score-writer 0.2.3

```
handoff/skill_0.2.3/
  assets/phrase_bank.json
  assets/corpus_fingerprints.bin
  assets/corpus_profile.dedup.candidate.json
  scripts/novelty_check.py
  CHANGELOG_SNIPPET.md
  INTEGRATION.md
```

See `INTEGRATION.md` for exact copy locations and optional intake/inspect
calls. Mandatory reading does not grow (`SKILL.md` 5,824 B, mandatory reading
26,484 B before and after); the phrase seeds and novelty line are optional
output of at most ~400 B and ~120 B.

## Tests

```bash
python -m pytest tests -q
```

Covered: z-score parity, seed clustering, reproducibility, rescue pairs,
phrase round-trip and source-note existence, stdlib/numpy token parity on all
670 songs, novelty example/self-containment, asset sizes, and phrase schema.

## Outputs

| path | contents |
|---|---|
| `out/validation.csv` | per-song parse/quality flags |
| `out/top_pairs.csv`, `out/groundtruth.txt` | calibrated similarity report |
| `out/clusters.json`, `out/dedupe_keep.txt` | dedupe result |
| `out/dedupe_report.md` | cluster report, sweep, listening list |
| `out/bands_shift.md` | full vs deduped Repo B bands |
| `out/vocal/` | vocal-only clustering and comparison |
| `docs/FINAL_REPORT.md` | phase-by-phase results and limitations |
| `docs/novelty_calibration.md` | threshold and false-positive rate |

Heavy generated artifacts (`out/corpus_dedup/`, `out/index_vocal.pkl`,
`out/pairs_raw_vocal.npz`) are gitignored and reproducible from the commands
above.

## Known limitations

- The default comparison uses each song's lead voice; use `--voice vocal`
  for a like-for-like vocal run. 26 songs have no usable Vocal.
- Z-threshold and coverage calibration is corpus-specific. Review the
  listening excerpts before trusting a new corpus.
- Phrase roles are inferred; the corpus has no lyrics.
- The phrase bank is mode-biased toward nahawand-like, reflecting the corpus.
- Novelty fingerprints use exact 8-token n-grams; rhythmically varied
  variants can score low. The check is advisory, not a plagiarism verdict.
- 12-TET only: maqam quarter-tones are already lost in the ABC.

See `abcsim/README.md` for implementation details.

## License

See `LICENSE`.
