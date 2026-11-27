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
SEED P012 sadr 16 beats Gm  b3:.5 4:.5 5:1 4:.5 b3:.5 2:1 ...
```

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
NOVELTY closest=suno-0123.abc containment=0.123 matched=8.4 beats status=ok
```

- `status=ok` below containment 0.05; `status=close` at or above it.
- Advisory only, in the same spirit as CRAFT flags. Do **not** fail a build,
  block release, or rewrite the melody automatically because of it.
- If `status=close`, mention the closest song/containment in the report and let
  the user decide.
- The script is stdlib-only and runs in ~0.3 s on a 30-bar score.

Threshold and false-positive rate are in
`docs/novelty_calibration.md` in the abcsim repository: containment >= 0.05,
0 false positives on 2,968 unrelated pairs, maximum unrelated containment
0.0165, Repo B's example song 0.000.

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

Measured with Repo B `scripts/measure_footprint.py` on a copy with this handoff
applied:

| metric | 0.2.2 | proposed 0.2.3 |
|---|---|---|
| SKILL.md | 5,824 B | 5,824 B |
| mandatory reading | 26,484 B | 26,484 B |
| example fill written | 1,241 B | 1,241 B |
| blueprint / skeleton | 3,444 / 1,352 B | 3,444 / 1,352 B |
| inspector success / failure | 11 / 20 words | 11 / 20 words |
| new optional output | 0 | <= 400 B phrases + <= 120 B novelty |

Mandatory reading does **not** grow. The phrase bank and fingerprint file are
read by scripts only.

## 5. Verification

From the abcsim repository:

```bash
python -m pytest tests/test_phrases.py tests/test_token_parity.py \
                 tests/test_novelty.py tests/test_assets_size.py -q
```

From a Repo B copy with the handoff applied:

```bash
python scripts/novelty_check.py assets/example_song.abc --assets assets
# NOVELTY closest=none containment=0.000 matched=0.0 beats status=ok
```

## 6. Rollback

Delete the three assets and `scripts/novelty_check.py`. No existing Repo B file
is modified by this handoff, so rollback is a file deletion.
