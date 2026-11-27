# Proposed CHANGELOG entry for abc-score-writer 0.2.3

```markdown
## 0.2.3

### Added (all optional; no mandatory reading added)
- `assets/phrase_bank.json`: 48 real vocal phrases (`schema: "phrase_bank/2"`,
  34,788 bytes) from the deduped 599-song SheetSage2 corpus, in the Blueprint
  tonic-relative `degree:beats` grammar. All 48 phrases fit `phrase_bytes <= 130`
  (45 x 8-beat, 3 x 16-beat). Intake may print at most 2-3 matching 8-beat
  phrases as optional seeds (<= 400 bytes). Read by a script, not by the agent.
- `scripts/novelty_check.py`: stdlib-only advisory check for how close a
  compiled melody is to the deduped corpus (supports full sets and bottom-k
  sketches). `validate_and_inspect.py` may call it after the CRAFT lines; print
  in the compact card only when `status=close` (<= 120 bytes) and always in
  verbose mode. Advisory only, not a release gate.
- `assets/corpus_fingerprints.bin`: 8-token novelty hashes for 596 deduped
  representatives (`bottom-256` sketch, 150,037 hashes, 630,382 bytes, stamped
  threshold `0.08`). Full-set (`full`, 1,027,911 B @0.08) and alternative
  sketch sizes (`k512`, `k128`, `k64`) are provided under `assets/alt/`.

### Changed
- None. `assets/corpus_profile.json` is unchanged.

### Candidate, not adopted
- `assets/corpus_profile.dedup.candidate.json` is the profile mined from the
  deduped corpus. abcsim's comparison found the largest percentile shift is
  3.6% of the full-corpus IQR (threshold 10%), so the recommendation is to
  **keep the current profile**. The candidate is included only for inspection.

### Footprint
Re-measure with Repo B's `scripts/measure_footprint.py` on the target commit;
the abcsim handoff adds no mandatory reading. Optional output when triggered:
<= 400 B for intake seeds, and <= 120 B for novelty only when `status=close` or
in verbose mode. (Note: the initial 0.2.3 draft cited 0.2.2 figures of
`5,824 B` / `26,484 B` / `11 / 20` words vs Repo B's 0.2.2 changelog values of
`5,808 B` / `26,468 B` / `13 / 32` words; always measure against the target commit.)
```
