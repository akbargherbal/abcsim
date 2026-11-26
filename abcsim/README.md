# abcsim: melodic similarity for SheetSage2 ABC scores

## Install
    pip install numpy numba matplotlib mido

## Data layout expected (the November_2026 bundle, unzipped)
    <ROOT>/TRANSCRIPTS/FADL_SHAKER/abc/*.json
    <ROOT>/TRANSCRIPTS/YT500/YT500/abc/*.json  (+ _manifest.jsonl)
    <ROOT>/TRANSCRIPTS/fadhl_shaker_selected_scores/*/score.abc
    <ROOT>/DATASET/fadhl_shaker_instrumental_18/abc/*.abc
To use your own folder of .abc files, edit corpus.py: load_all() only has to return
a list of dicts with keys: id, corpus, artist, title, abc (the ABC text), dup (or None).

## Quick start on YOUR folder of .abc files (any number, nested folders are fine)
    python abcsim/run_validate.py   /path/to/my_abc_folder out
    python abcsim/run_similarity.py /path/to/my_abc_folder out
    python abcsim/run_report.py     out
    python abcsim/run_chordmap.py   /path/to/my_abc_folder out
If the folder has no TRANSCRIPTS/ sub-folder, every *.abc inside it is loaded automatically.
Delete out/index.pkl whenever the set of songs changes (it is a cache).
Runtime is roughly (songs^2) : 25 songs = 3 s, 670 songs = ~10 min on one core.

## Run on the November_2026 bundle (from the folder that contains abcsim/)
    python abcsim/run_validate.py   ROOT out     # 1 min   -> out/validation.csv
    python abcsim/run_chordmap.py   ROOT out     # seconds -> chord_progressions.csv, chordmap.png
    python abcsim/run_similarity.py ROOT out     # ~10 min on 1 core for 670 songs (224k pairs)
    python abcsim/run_report.py     out          # -> top_pairs.csv, groundtruth.txt, null_hist.png
    python abcsim/export_segments.py ROOT out 8  # -> out/listen/*.mid  (A passage, pause, B passage)
    python abcsim/run_eval.py       ROOT out     # ~30 min: excerpt-length / noise test -> eval_excerpt.png

## Near-duplicate clusters (dedupe)
    python abcsim/cluster_dups.py out
        # -> out/clusters.json, out/dedupe_keep.txt, out/dedupe_report.md,
        #    out/listen_pairs.tsv, out/rescue_pairs.tsv
        # uses the cached index.pkl + pairs_raw.npz (no all-pairs recompute)
        # --z-min 50 --min-coverage 0.25  (both calibrated; see out/dedupe_report.md)
        # --no-rescue disables the unweighted second pass; --rescue-coverage 0.5,
        # --rescue-z-min 10, --rescue-global-min 0 tune it.
    python abcsim/export_segments.py ROOT out --pairs out/listen_pairs.tsv --tag cal
        # -> out/listen/*_cal_*.mid, for human listening near the threshold
    python abcsim/export_segments.py ROOT out --pairs out/rescue_pairs.tsv --tag rescue
        # -> out/listen/*_rescue_*.mid for the rescue-pass candidates (long uniform segment)

`dedupe_keep.txt` lists one representative per cluster plus every singleton; the
original .abc files are never modified.  The seed check (`suno-0432` /
`suno-0620`) must pass; it is covered by `tests/test_clusters_seed.py`.

## Deduped corpus and band comparison (Phase 3)
    python abcsim/export_dedup_corpus.py CORPUS out
        # -> out/corpus_dedup/ (only dedupe_keep.txt; originals untouched)
    python <repoB>/scripts/mine_corpus.py --corpus CORPUS --out out/profile_full.json
    python <repoB>/scripts/mine_corpus.py --corpus out/corpus_dedup --out out/profile_dedup.json
    python abcsim/compare_bands.py out
        # -> out/bands_shift.md + handoff/skill_0.2.3/assets/corpus_profile.dedup.candidate.json
The full-corpus mine must reproduce Repo B's committed `assets/corpus_profile.json`
before the comparison is trusted (it does on v0.2.2).

## Vocal-only index and clustering (Phase 4)
    python abcsim/build_index.py CORPUS --voice vocal --cache out/index_vocal.pkl
        # 644 songs, 26 without a usable Vocal are skipped and counted
    python abcsim/run_similarity.py CORPUS out --voice vocal
        # -> out/pairs_raw_vocal.npz (~10 min, cached)
    python abcsim/cluster_dups.py out/vocal --index out/index_vocal.pkl \
        --pairs out/pairs_raw_vocal.npz --validation out/validation.csv
    python abcsim/compare_cluster_runs.py out
        # -> out/vocal/clusters_lead_vs_vocal.md
`--voice lead` is the default and keeps the old cache/output paths.

## Phrase bank (Phase 5)
    python abcsim/export_phrases.py CORPUS out
        # -> handoff/skill_0.2.3/assets/phrase_bank.json (<= 60 KB)
Uses only the deduped set and Vocal streams, writes Repo B's degree:beats grammar,
and labels roles as `role_hint` (no lyrics in the corpus).

## Novelty fingerprints (Phase 6)
    python abcsim/export_fingerprints.py CORPUS out
        # -> handoff/skill_0.2.3/assets/corpus_fingerprints.bin (<= 1 MB)
    python abcsim/calibrate_novelty.py CORPUS out
        # -> docs/novelty_calibration.md, out/novelty_calibration.json
    python handoff/skill_0.2.3/scripts/novelty_check.py song.abc --assets handoff/skill_0.2.3/assets
        # one advisory line; stdlib only; copy it beside Repo B's abc_common.py
The 8-token tokenizer in `novelty_check.py` is parity-tested against
`features.tokens_from_notes` on all 670 songs.

## Files
    parse.py     ABC -> notes (onset in quarter-beats, midi, duration, bar). Handles L:1/16 & 1/32, M: changes,
                 Z multi-bar rests, ties, key signatures, inline [K:], chords.
    features.py  notes -> tokens (interval, IOI-ratio class): transposition and tempo invariant.
    align.py     Smith-Waterman local alignment (numba), tokens weighted by rarity; a global
                 (Needleman-Wunsch) score is used only by the dedupe rescue gate.
    build_index.py  parse everything once, cache to out/index.pkl (--voice lead|vocal|ins).
    run_similarity.py  all-pairs alignment; --voice vocal writes pairs_raw_vocal.npz.
    stats.py     shared z-score calibration (score ~ log(nA*nB), robust MAD sigma).
    cluster_dups.py  near-duplicate clusters + dedupe_keep.txt; clique guard against chaining;
                 representative chosen by vocal quality, then validation flags, then bar count;
                 optional rescue pass for rhythmic variants the weighted alignment misses.
    export_dedup_corpus.py  copy only dedupe_keep.txt files into out/corpus_dedup/.
    compare_bands.py  Repo B profile percentiles/forms/chords/keys, full vs deduped.
    compare_cluster_runs.py  pair-level lead vs vocal clustering comparison.
    export_phrases.py  deduped Vocal phrases in Repo B degree grammar -> phrase_bank.json.
    export_fingerprints.py  8-token novelty hashes -> corpus_fingerprints.bin.
    calibrate_novelty.py  positive/negative calibration -> docs/novelty_calibration.md.

## Known limits
- The default run compares only the "lead" voice (most notes). Songs whose lead differs (Vocal vs Ins) can be missed;
  use `--voice vocal` / `--voice ins` for separate like-for-like runs. The vocal run skips 26 songs with no Vocal.
- 12-TET only: maqam quarter-tones are already lost in the ABC.
- Repeated-note runs score high; use trivial_fraction / distinct_tokens columns to filter them.
- Phrase `role_hint` is inferred from cadence and phrase length; the corpus has no lyrics.
- Novelty fingerprints use exact 8-token n-grams, so a rhythmically varied variant can score low; the check is advisory.
