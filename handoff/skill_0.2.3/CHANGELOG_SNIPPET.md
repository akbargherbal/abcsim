# Proposed CHANGELOG entry for abc-score-writer 0.2.3

```markdown
## 0.2.3

### Added (all optional; no mandatory reading added)
- `assets/phrase_bank.json`: 48 real vocal phrases from the deduped 599-song
  SheetSage2 corpus, in the Blueprint `degree:beats` grammar. Intake may print
  at most 2-3 matching phrases as optional seeds (<= 400 bytes). The file is
  read by a script, not by the agent.
- `scripts/novelty_check.py`: stdlib-only advisory check for how close a
  compiled melody is to the deduped corpus. `validate_and_inspect.py` may call
  it after the CRAFT lines and print one line (<= 120 bytes). It is advisory,
  not a release gate.
- `assets/corpus_fingerprints.bin`: 8-token novelty hashes for 596 deduped
  representatives (249,371 hashes, 1,027,894 bytes, full set, no sketch).

### Changed
- None. `assets/corpus_profile.json` is unchanged.

### Candidate, not adopted
- `assets/corpus_profile.dedup.candidate.json` is the profile mined from the
  deduped corpus. abcsim's comparison found the largest percentile shift is
  3.6% of the full-corpus IQR (threshold 10%), so the recommendation is to
  **keep the current profile**. The candidate is included only for inspection.

### Footprint (measured with `scripts/measure_footprint.py`)
| metric | 0.2.2 | proposed 0.2.3 |
|---|---|---|
| SKILL.md | 5,824 B | 5,824 B |
| mandatory reading | 26,484 B | 26,484 B |
| example fill written | 1,241 B | 1,241 B |
| blueprint / skeleton | 3,444 / 1,352 B | 3,444 / 1,352 B |
| inspector success / failure | 11 / 20 words | 11 / 20 words |
| new optional output | 0 | <= 400 B phrases + <= 120 B novelty |

The large assets are script-only and never loaded into the agent's context.
```
