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

## Files
    parse.py     ABC -> notes (onset in quarter-beats, midi, duration, bar). Handles L:1/16 & 1/32, M: changes,
                 Z multi-bar rests, ties, key signatures, inline [K:], chords.
    features.py  notes -> tokens (interval, IOI-ratio class): transposition and tempo invariant.
    align.py     Smith-Waterman local alignment (numba), tokens weighted by rarity.
    build_index.py  parse everything once, cache to out/index.pkl.

## Known limits
- Only the "lead" voice (most notes) of each song is compared. Songs whose lead differs (Vocal vs Ins) can be missed;
  fix = also compare Vocal<->Vocal and Ins<->Ins (4x compute).
- 12-TET only: maqam quarter-tones are already lost in the ABC.
- Repeated-note runs score high; use trivial_fraction / distinct_tokens columns to filter them.
