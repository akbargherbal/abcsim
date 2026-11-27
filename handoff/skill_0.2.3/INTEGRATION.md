# Integration: abcsim handoff into abc-score-writer 0.2.3

This folder is a **ready-to-copy handoff**. Nothing here has been applied to
Repo B. A human decides what to adopt.

## Copy map

```
handoff/skill_0.2.3/assets/phrase_bank.json
    -> <repoB>/assets/phrase_bank.json
handoff/skill_0.2.3/assets/corpus_fingerprints.bin
    -> <repoB>/assets/corpus_fingerprints.bin
handoff/skill_0.2.3/assets/corpus_profile.dedup.candidate.json
    -> <repoB>/assets/corpus_profile.dedup.candidate.json   (candidate only)
handoff/skill_0.2.3/scripts/novelty_check.py
    -> <repoB>/scripts/novelty_check.py                     (beside abc_common.py)
```

`novelty_check.py` imports `abc_common` from its own directory, so it must sit
in Repo B's `scripts/`. No third-party package is needed.

## 1. Intake: optional phrase seeds

`scripts/intake_lyrics.py` already prints the style/section/line table. After
it writes `intake.json` (and the skeleton), intake **may** print 2-3 optional
phrase seeds. This is optional output, not mandatory reading.

Suggested filter for each lyric line:

- `cadence_class` matches the line role: `sadr` -> `sadr`, `ajuz` -> `ajuz`.
- `beats` matches the budget: 16 for a shatr (4 bars of 4/4), 8 for a short
  line. For 2/4 songs use the beat budget, not a bar count.
- **Print 8-beat seeds only.** The shipped bank has 45 phrases at 8 beats and
  only 3 at 16 beats (all three fit the byte budget), so a 16-beat request will
  usually come back empty. If a 16-beat seed is offered, say it is one of three
  and still check the bar sum.
- `mode_hint` is compatible with the style maqam (`kurd-like`, `hijaz-like`,
  `nahawand-like`, `rast-like`, `bayati-like`, `saba-like`). If unsure, skip
  the mode filter rather than forcing a mismatch. Mode coverage is uneven:
  kurd/hijaz/rast have 8 phrases each, nahawand 15, bayati **1** (reported in
  `counts.mode_shortfall`), so for a Bayati line fall back to `mode=any`
  instead of forcing the single available phrase.
- Prefer `register` `mid` or `high`; `low` is available but may sit under the
  verse register.

Print at most three, each one line, and cap the whole block at **400 bytes**:

```
SEED P012 sadr 8b 4:.5 5:1 b3:.5 ...
```

**Degrees are tonic-relative** (no key or transposition is carried in the phrase
string; `1` is the song's tonic in octave 4, with `+`/`-` octave suffixes). Do not
print a source key in the `SEED` line.

Every phrase carries `phrase_bytes` and `fits_seed_budget`; the bank was built
with `--max-phrase-bytes 130`, so all 48 phrases fit the 130-byte seed budget
and three seeds fit the 400-byte block with room to spare. The bank is
`schema: "phrase_bank/2"`; the new fields are listed in its `grammar` block.

The agent may use a seed as a starting phrase, or ignore it. Do not paste a
seed into a bar without checking the bar sum and the line's syllable budget.

The JSON is 34.8 KB (34,788 bytes) and is loaded by the intake script, never
pasted into the agent's context. Fields: `beats`, `phrase`, `end_degree`,
`cadence_class`, `role_hint`, `mode_hint`, `source_id`, `source_bars`,
`register`, `source_key`, `source_midi`, `cluster`, `id`, plus `phrase_bytes`
and `fits_seed_budget` (schema 2).

`role_hint` is heuristic: the corpus has no lyrics, so sadr/ajuz is inferred
from cadence and phrase length only.

## 2. Validate and inspect: one advisory novelty line

`scripts/validate_and_inspect.py` already prints `CRAFT FLAGS` (or `CRAFT OK`)
in its compact report. After those lines, it **may** call:

```python
subprocess.run([
    sys.executable,
    os.path.join(script_dir, "novelty_check.py"),
    abc_path,
    "--assets", os.path.join(skill_root, "assets"),
], check=False)
```

Output is at most one line:

```
NOVELTY closest=suno-0123.abc containment=0.123 matched=8.4 beats status=close
```

- `status=ok` below the bank's threshold (**0.08** for the shipped `bottom-256`
  default); `status=close` at or above it (`novelty_check.py` reads the
  threshold from the `.bin` header unless `--threshold` is passed).
- **Compact vs. verbose output:** print the compact-card line **only when
  `status=close`** (so a normal `status=ok` build adds zero words to the compact
  success card); always print in verbose mode.
- Advisory only, in the same spirit as CRAFT flags. Do **not** fail a build,
  block release, or rewrite the melody automatically because of it.
- If `status=close`, mention the closest song/containment in the report and let
  the user decide.
- The script is stdlib-only and runs in ~0.3 s on a 30-bar score.

Threshold and false-positive rate for the shipped `bottom-256` default
(630,382 B) are in `docs/novelty_calibration.md` in the abcsim repository
(alternatives `full`, `k512`, `k128`, `k64` are in `assets/alt/` and compared in
`docs/fingerprint_options.md`): containment >= **0.08**, 45 / 47 cluster
positives caught, 0 false positives on 2,968 unrelated pairs (max 0.0199) and 0
false positives on 592 whole-bank unrelated queries (max 0.0640, p99 0.0414).

These figures were reconfirmed in `handoff-0.2.3-r3` by running every positive through
`novelty_check.check()` itself (the call above). Pin `handoff-0.2.3-r3` or later:
`handoff-0.2.3-r2` has a broken `check()` (crash on sketch banks, silent `status=ok` on the
full bank).

## 3. Candidate corpus profile: not adopted

`assets/corpus_profile.dedup.candidate.json` is the Repo B profile mined from
the deduped 599-file corpus. It is a **candidate**, not part of the proposed
0.2.3 defaults.

abcsim's comparison (`out/bands_shift.md`) found:

- largest percentile shift: **3.6% of the full-corpus IQR** (threshold 10%);
- forms, chord-quality/loop ranks, and key distribution are essentially
  unchanged (counts drop because 71 duplicate files are removed).

Recommendation: **keep the current `assets/corpus_profile.json`**. If a human
later decides to adopt the candidate, rename it over `corpus_profile.json` and
record the change; no code change is needed.

## 4. Footprint

Re-measure with Repo B's `scripts/measure_footprint.py` on the target commit;
the abcsim handoff adds **no mandatory reading**.

- Mandatory reading does **not** grow: `phrase_bank.json` (34,788 B) and
  `corpus_fingerprints.bin` (630,382 B) are read by scripts only and never
  loaded into the agent's context.
- Optional script output: `<= 400 B` for intake seeds, `0 B` on the compact
  success card when `status=ok`, and `<= 120 B` only when `status=close` or in
  verbose mode.
- Note on earlier numbers: the initial 0.2.3 draft cited 0.2.2 baseline figures
  of `5,824 B` (`SKILL.md`), `26,484 B` (mandatory reading), and `11 / 20` words
  (inspector success/failure), whereas Repo B's 0.2.2 changelog recorded
  `5,808 B`, `26,468 B`, and `13 / 32` words. Always measure directly against the
  target Repo B commit.

## 5. Verification

From the abcsim repository:

```bash
python -m pytest tests/test_phrases.py tests/test_token_parity.py \
                 tests/test_novelty.py tests/test_assets_size.py \
                 tests/test_mode_hint.py -q
```

From a Repo B copy with the handoff applied:

```bash
python scripts/novelty_check.py assets/example_song.abc --assets assets
# NOVELTY closest=... containment=... matched=... beats status=ok
```

## 6. Limitations

What these assets do **not** show or guarantee:

- **Seeds are unproven to improve generation:** the bank supplies real corpus
  contours, not an A/B-tested quality boost.
- **`role_hint` is heuristic:** the corpus has no lyrics, so `sadr`/`ajuz` is
  inferred from cadence and phrase length only.
- **Register and mode coverage are skewed:** the bank is predominantly mid/high
  register (`16` mid, `29` high, `3` low; `45` at 8 beats and `3` at 16 beats),
  and `bayati-like` has only `1` phrase (`counts.mode_shortfall`).
- **AI-generated source corpus:** the 670 files are Suno outputs transcribed by
  SheetSage2, with 12-TET quantization (no quarter-tones) and no quality/rating
  filter.
- **Exact 8-gram matching misses rhythmic variants:** 2 of 47 cluster pairs
  score below `0.08` with `bottom-256` (1 of 47 scored below `0.05` in the
  earlier full-set check). Sketch `matched=` beats is a lower bound and requires
  at least 3 matching n-grams.

## 7. Rollback

Delete the three assets (plus `assets/alt/` if copied) and
`scripts/novelty_check.py`. No existing Repo B file is modified by this handoff,
so rollback is a file deletion.
