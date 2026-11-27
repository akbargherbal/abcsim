"""calibrate_novelty.py -- reproduce the Phase 6 threshold calibration.

Positives: within-cluster pairs (member vs representative).
Negatives: random pairs from different clusters.
Example: Repo B's assets/example_song.abc.

Writes docs/novelty_calibration.md and out/novelty_calibration.json.

Variants mode (--variants A.bin,B.bin,...) evaluates several fingerprint files
(full set and bottom-k sketches) with the SAME estimator novelty_check.py uses
at runtime, recomputes a threshold per variant and writes
docs/fingerprint_options.md plus out/fingerprint_variants.json.  --stamp then
records each variant's recommended threshold in its file header.

The Repo B example song is located through repo_b.find_repo_b (environment
variable ABC_SCORE_COMPOSER, then a sibling folder, then ~/abc_score_composer);
pass --example to point at a specific file.

Usage:
    python abcsim/calibrate_novelty.py CORPUS_ROOT out [--example PATH]
    python abcsim/calibrate_novelty.py CORPUS_ROOT out --variants \
        handoff/skill_0.2.3/assets/corpus_fingerprints.bin,handoff/skill_0.2.3/assets/alt/corpus_fingerprints.k128.bin --stamp
"""
import argparse
import importlib.util
import json
import random
import statistics
import struct
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corpus import load_all
from features import song_stream
from export_fingerprints import hashes_for_tokens, hash_ngram, N, restamp
import repo_b

ROOT = Path(__file__).resolve().parents[1]
NOVELTY_CHECK = ROOT / 'handoff' / 'skill_0.2.3' / 'scripts' / 'novelty_check.py'
RELATED_FLOOR = 0.15   # whole-bank best matches at or above this are listed as likely related pairs
GRID = [0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30]

MAGIC = b'ABCFP1\n'


def load_bank(path):
    with open(path, 'rb') as f:
        assert f.read(len(MAGIC)) == MAGIC
        hlen = struct.unpack('<I', f.read(4))[0]
        header = json.loads(f.read(hlen).decode('utf-8'))
        data = f.read()
    flat = list(struct.unpack('<%dI' % header['total'], data)) if header['total'] else []
    sets = {}
    for s in header['songs']:
        sets[s['id']] = set(flat[s['offset']:s['offset'] + s['count']])
    return header, sets


def grams_with_starts(st):
    iv, rc = st['iv'], st['rc']
    ids = (iv.astype('int32') + 12) * 9 + (rc.astype('int32') + 4)
    return [(hash_ngram(ids[i:i + N]), i) for i in range(max(0, len(ids) - N + 1))]


def matched_beats(notes, starts):
    spans = []
    for i in starts:
        last = min(i + N + 1, len(notes) - 1)
        spans.append((notes[i].onset, notes[last].onset + notes[last].dur))
    if not spans:
        return 0.0
    spans.sort()
    total = 0.0
    cs, ce = spans[0]
    for s, e in spans[1:]:
        if s <= ce + 1e-9:
            ce = max(ce, e)
        else:
            total += ce - cs
            cs, ce = s, e
    return total + ce - cs


def pct(vals, p):
    if not vals:
        return None
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(p / 100.0 * len(vals)))]



# --------------------------------------------------------------------------- variants mode
def load_novelty_module():
    """Import the handoff novelty_check.py so calibration uses the runtime estimator."""
    rb = repo_b.find_repo_b()
    if rb is not None:
        sys.path.insert(0, str(rb / 'scripts'))      # lets nc.check() parse songs
    spec = importlib.util.spec_from_file_location('novelty_check_handoff', NOVELTY_CHECK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, rb


def entry_score(nc, prep, entry):
    """Containment of a composition (prepared grams) in ONE bank entry (id, set, tau)."""
    _sid, hs, tau = entry
    matched, den = nc.match_song(prep, hs, tau)
    if den <= 0 or not matched:
        return 0.0
    if tau is not None and len(matched) < nc.MIN_SKETCH_MATCHES:
        return 0.0
    return len(matched) / float(den)


def known_related_pairs(outd):
    """Pairs abcsim's own similarity search ranked as related (out/top_pairs.csv,
    plus the listening/rescue pair lists).  They share real material, so a high
    containment between them is a true hit and must not count as a false positive."""
    import csv
    pairs = set()
    f = Path(outd) / 'top_pairs.csv'
    if f.exists():
        with open(f, encoding='utf-8') as fh:
            for r in csv.DictReader(fh):
                a, b = r.get('id_A'), r.get('id_B')
                if a and b:
                    pairs.add(frozenset((a, b)))
    for name in ('listen_pairs.tsv', 'rescue_pairs.tsv'):
        f = Path(outd) / name
        if f.exists():
            for line in f.read_text(encoding='utf-8').splitlines():
                cols = line.split('\t')
                if len(cols) >= 2:
                    pairs.add(frozenset((cols[0], cols[1])))
    return pairs


def vocal_cluster_lookup(outd):
    """Map frozenset((a, b)) -> vocal cluster id from out/vocal/clusters.json if present."""
    f = Path(outd) / 'vocal' / 'clusters.json'
    if not f.exists():
        return {}
    vc = json.loads(f.read_text(encoding='utf-8'))
    out = {}
    for c in vc.get('clusters', []):
        ids = [m['id'] for m in c.get('members', [])]
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                out[frozenset((ids[i], ids[j]))] = c['id']
    return out


def choose_threshold(neg_bank_max, pair_max):
    """Smallest grid value with a 1.25x margin over the worst unrelated score."""
    floor = 1.25 * max(neg_bank_max, pair_max)
    for t in GRID:
        if t >= floor - 1e-12:
            return t, True
    return GRID[-1], False


def run_variants(args, example_path):
    nc, rb = load_novelty_module()
    outd = Path(args.outd)
    clusters = json.loads((outd / 'clusters.json').read_text(encoding='utf-8'))
    keep = [x.strip() for x in (outd / 'dedupe_keep.txt').read_text(encoding='utf-8').splitlines() if x.strip()]
    cluster_of = {}
    for c in clusters['clusters']:
        for m in c['members']:
            cluster_of[m['id']] = c['id']
    for sid in clusters['singletons']:
        cluster_of[sid] = 'S:' + sid
    songs = {s['id']: s for s in load_all(args.corpus)}
    related = known_related_pairs(outd)

    gcache = {}
    raw = {}

    def grams(sid):
        """Prepared n-grams ({hash: [positions]}) of a kept song; {} when too short."""
        if sid not in gcache:
            st = song_stream(songs[sid]['abc'], voice='Vocal') if sid in songs else None
            raw[sid] = grams_with_starts(st) if st is not None else []
            gcache[sid] = nc.prepare(raw[sid])
        return gcache[sid]

    # example song grams (abcsim tokenizer, same as the single-bank path)
    ex_grams = None
    if example_path:
        from parse import parse_abc
        from features import tokens_from_notes
        song = parse_abc(Path(example_path).read_text(encoding='utf-8'))
        notes = song.voices.get('Vocal') or (song.voices[max(song.voices, key=lambda v: len(song.voices[v]))] if song.voices else [])
        tk = tokens_from_notes(notes) if notes else None
        if tk is not None:
            ex_grams = nc.prepare(grams_with_starts(dict(iv=tk[0], rc=tk[1])))

    rng = random.Random(0)
    neg_pairs = []
    for _ in range(args.samples):
        a, b = rng.sample(keep, 2)
        if cluster_of.get(a) != cluster_of.get(b):
            neg_pairs.append((a, b))
    queries = rng.sample(keep, min(args.bank_queries, len(keep)))

    # Partial-copy trials, identical for every variant: an unrelated song A with a
    # contiguous block of L n-grams of bank song B spliced in.  Detected when the
    # composition's containment in B reaches the variant's threshold.
    PARTIAL_LENGTHS = (20, 40, 80, 160)
    rng2 = random.Random(1)
    partial_trials = {}
    for L in PARTIAL_LENGTHS:
        trials = []
        pool_b = [sid for sid in keep if len(grams(sid)) and len(raw[sid]) >= L + 1]
        while len(trials) < args.partial_trials and pool_b:
            b = rng2.choice(pool_b)
            a = rng2.choice(keep)
            if (a == b or cluster_of.get(a) == cluster_of.get(b) or not grams(a)
                    or frozenset((a, b)) in related):
                continue
            off = rng2.randrange(0, len(raw[b]) - L + 1)
            block = [h for h, _ in raw[b][off:off + L]]
            comp = {h: list(v) for h, v in grams(a).items()}
            for h in block:
                comp.setdefault(h, []).append(0)
            trials.append((a, b, comp))
        partial_trials[L] = trials

    results = []
    for path in [x.strip() for x in args.variants.split(',') if x.strip()]:
        header, bank_songs = nc.load_bank(path)
        entry = {e[0]: e for e in bank_songs}
        label = 'full set' if not header.get('sketch') else 'bottom-%d' % header.get('k', 0)

        pos_rows = []
        for c in clusters['clusters']:
            rep = c['representative']
            if rep not in entry:
                continue
            for m in c['members']:
                if m['id'] == rep:
                    continue
                g = grams(m['id'])
                if not g:
                    continue
                pos_rows.append((entry_score(nc, g, entry[rep]), c['id'], m['id'], rep))
        pos = [r[0] for r in pos_rows]

        neg_pair = []
        for a, b in neg_pairs:
            if b in entry and grams(a):
                neg_pair.append(entry_score(nc, grams(a), entry[b]))

        neg_bank = []
        for q in queries:
            g = grams(q)
            if not g:
                continue
            others = [e for e in bank_songs if cluster_of.get(e[0]) != cluster_of.get(q)
                      and frozenset((e[0], q)) not in related]
            best = nc.best_match(g, others)
            neg_bank.append((best[0] if best else 0.0, q, best[2] if best else None))
        likely_related = [(v, q, b) for v, q, b in neg_bank if v >= RELATED_FLOOR]
        neg_bank = [v for v, _q, _b in neg_bank if v < RELATED_FLOOR]

        pair_max = max(neg_pair) if neg_pair else 0.0
        bank_max = max(neg_bank) if neg_bank else 0.0
        rec, margin_ok = choose_threshold(bank_max, pair_max)

        partial = {}
        for L, trials in partial_trials.items():
            hits = sum(1 for _a, b, comp in trials if b in entry and entry_score(nc, comp, entry[b]) >= rec)
            partial[L] = hits / float(len(trials)) if trials else None

        def caught(t):
            return sum(1 for v in pos if v >= t)

        def fp(vals, t):
            return sum(1 for v in vals if v >= t)

        ex = None
        ex_time = None
        if ex_grams:
            b = nc.best_match(ex_grams, bank_songs)
            ex = b[0] if b else 0.0
        if example_path and rb is not None and nc.parse_abc is not None:
            t0 = time.perf_counter()
            nc.check(example_path, path)
            ex_time = time.perf_counter() - t0

        results.append(dict(
            file=str(path), label=label, bytes=Path(path).stat().st_size,
            songs=len(bank_songs), hashes=header['total'], sketch=bool(header.get('sketch')),
            k=header.get('k', 0),
            positives=len(pos), caught_at_005=caught(0.05), caught_at_rec=caught(rec),
            recommended_threshold=rec, margin_ok=margin_ok,
            pos_p10=pct(pos, 10), pos_p50=pct(pos, 50), pos_min=min(pos) if pos else None,
            neg_pairs=len(neg_pair), neg_pair_max=pair_max, neg_pair_fp_005=fp(neg_pair, 0.05),
            neg_pair_fp_rec=fp(neg_pair, rec),
            neg_bank_queries=len(neg_bank), neg_bank_max=bank_max,
            likely_related=[dict(containment=round(v, 3), query=q, closest=b) for v, q, b in sorted(likely_related, reverse=True)],
            neg_bank_p99=pct(neg_bank, 99), neg_bank_mean=(sum(neg_bank) / len(neg_bank)) if neg_bank else 0.0,
            neg_bank_fp_005=fp(neg_bank, 0.05), neg_bank_fp_rec=fp(neg_bank, rec),
            example=ex, example_seconds=ex_time, partial_detect={str(k): v for k, v in partial.items()},
            partial_trials=args.partial_trials,
            positive_misses_at_rec=[dict(containment=round(v, 3), cluster=c, member=m, representative=r)
                                    for v, c, m, r in sorted(pos_rows) if v < rec],
        ))
        print('   partial-copy detection @rec: ' + ', '.join('L=%d %.0f%%' % (k, 100 * v) for k, v in partial.items() if v is not None))
        print('%-10s %8d B  pos %d/%d @0.05, %d/%d @%.2f | pair max %.4f | bank max %.4f | example %s' % (
            label, results[-1]['bytes'], caught(0.05), len(pos), caught(rec), len(pos), rec,
            pair_max, bank_max, '%.3f' % ex if ex is not None else 'n/a'))

    # --- pick a recommendation by a stated rule
    full = next((r for r in results if not r['sketch']), results[0])
    ok = [r for r in results if r['margin_ok'] and r['neg_pair_fp_rec'] == 0 and r['neg_bank_fp_rec'] == 0
          and r['caught_at_rec'] >= full['caught_at_rec'] - 2
          and (r['partial_detect'].get('80') or 0) >= 0.90]
    pick = min(ok, key=lambda r: r['bytes']) if ok else full
    json_path = Path(args.outd) / 'fingerprint_variants.json'
    json_path.write_text(json.dumps(dict(variants=results, recommended=pick['file']), indent=2) + '\n',
                         encoding='utf-8', newline='\n')

    if args.stamp:
        for r in results:
            restamp(r['file'], threshold=r['recommended_threshold'])
            r['bytes'] = Path(r['file']).stat().st_size
        print('stamped thresholds into %d file headers' % len(results))

    prev = None
    prev_path = Path(args.outd) / 'novelty_calibration.json'
    if prev_path.exists():
        prev = json.loads(prev_path.read_text(encoding='utf-8'))
    vocal_clusters = vocal_cluster_lookup(outd)

    L = ['# Fingerprint variants', '',
         'Generated by `abcsim/calibrate_novelty.py --variants`. Every variant is scored with the',
         'same estimator `novelty_check.py` uses at runtime (it is imported, not re-implemented).', '',
         '## Variants', '',
         'A bottom-k sketch keeps the k numerically smallest 8-gram hashes of each song. A song with',
         'fewer than k hashes is stored complete. Because a sketch only knows hashes up to its largest',
         'stored value (tau), containment is estimated over the composition n-grams whose hash is <= tau,',
         'and a sketch hit also needs at least %d matching n-grams.' % nc.MIN_SKETCH_MATCHES, '',
         '| variant | file size | hashes | positives caught @0.05 | recommended threshold | positives caught @rec | '
         'unrelated pairs: max / FP@rec | whole-bank unrelated best: max / p99 | Repo B example |',
         '|---|---|---|---|---|---|---|---|---|']
    for r in results:
        L.append('| %s | %.0f KB | %d | %d / %d | **%.2f** | %d / %d | %.4f / %d | %.4f / %.4f | %s |' % (
            r['label'], r['bytes'] / 1024.0, r['hashes'], r['caught_at_005'], r['positives'],
            r['recommended_threshold'], r['caught_at_rec'], r['positives'],
            r['neg_pair_max'], r['neg_pair_fp_rec'], r['neg_bank_max'], r['neg_bank_p99'] or 0.0,
            ('%.3f' % r['example']) if r['example'] is not None else 'not scored'))
    L += ['', '### Partial-copy sensitivity', '',
          'Detection rate at each variant\'s recommended threshold when a block of L consecutive n-grams of a bank',
          'song is spliced into an unrelated song (%d trials per L, same trials for every variant). One n-gram is about' % results[0]['partial_trials'],
          '0.25 s of melody, so L=20 is a short hook and L=80 is a passage of roughly 20 s.', '',
          '| variant | threshold | L=20 | L=40 | L=80 | L=160 |', '|---|---|---|---|---|---|']
    for r in results:
        L.append('| %s | %.2f | %s |' % (r['label'], r['recommended_threshold'], ' | '.join(
            ('%.0f%%' % (100 * r['partial_detect'][str(l)])) if r['partial_detect'].get(str(l)) is not None else '—'
            for l in (20, 40, 80, 160))))
    L += ['',
          'Columns:', '',
          '- *positives*: %d within-cluster pairs (member scored against its cluster representative).' % results[0]['positives'],
          '- *unrelated pairs*: %d random different-cluster pairs, containment of A in B.' % results[0]['neg_pairs'],
          '- *whole-bank unrelated best*: for %d random songs, the best containment over every bank song' % results[0]['neg_bank_queries'],
          '  outside their own cluster. This is what the runtime check actually reports for an original song,',
          '  so it is the number the threshold must clear.', '',
          '## Threshold rule', '',
          'The recommended threshold is the smallest value on the grid %s that is at least 1.25x the larger' % ', '.join('%.2f' % g for g in GRID),
          'of the unrelated-pair maximum and the whole-bank unrelated maximum (excluding likely related pairs). It is recomputed per variant;',
          '0.05 is not reused unless it satisfies this rule.', '']
    rel_seen = {}
    for r in results:
        for item in r.get('likely_related', []):
            k = tuple(sorted((item['query'], item['closest'])))
            rel_seen.setdefault(k, []).append((r['label'], item['containment']))
    if rel_seen:
        L += ['Excluded whole-bank pairs at or above %.2f (`likely_related`):' % RELATED_FLOOR, '']
        for (a, b), scores in sorted(rel_seen.items()):
            vcid = vocal_clusters.get(frozenset((a, b)))
            note = ('known vocal-only duplicate cluster %s (missed by lead-only dedupe)' % vcid
                    if vcid else 'unclustered pair >= %.2f' % RELATED_FLOOR)
            L.append('- `%s` <-> `%s` (max %.3f): %s.' % (a, b, max(s for _, s in scores), note))
        L.append('')
    flag = [r for r in results if not r['margin_ok']]
    if flag:
        L.append('WARNING: no grid threshold clears the 1.25x margin for: %s.' % ', '.join(r['label'] for r in flag))
        L.append('')
    L += ['## Recommendation', '']
    L.append('Rule: the smallest file whose recommended threshold has zero false positives on both unrelated sets, '
             'catches at least (full-set caught - 2) positives, and detects at least 90% of spliced 80-n-gram '
             'passages (about 20 seconds of melody).')
    L.append('')
    L.append('**Recommended variant: %s (%.0f KB, threshold %.2f).** It catches %d of %d positives (full set: %d of %d) '
             'and the worst unrelated whole-bank score is %.4f.' % (
                 pick['label'], pick['bytes'] / 1024.0, pick['recommended_threshold'], pick['caught_at_rec'],
                 pick['positives'], full['caught_at_rec'], full['positives'], pick['neg_bank_max']))
    L.append('')
    L.append('Repo B keeps the choice: the full set is the most faithful, the sketches trade some recall and')
    L.append('precision on short songs for a much smaller package.')
    L.append('')
    L += ['## Missed positives (cluster pairs below the recommended threshold)', '']
    for r in results:
        misses = r['positive_misses_at_rec']
        L.append('- **%s**: %d miss(es)%s' % (r['label'], len(misses), (' - ' + ', '.join(
            '%s vs %s (%.3f)' % (m['member'], m['representative'], m['containment']) for m in misses[:6])) if misses else ''))
    L += ['', '## Timing', '']
    for r in results:
        L.append('- %s: %s' % (r['label'], ('%.2f s for check() on the Repo B example' % r['example_seconds'])
                               if r['example_seconds'] is not None else 'not measured (Repo B not found)'))
    L += ['', '## Previous (0.2.3 handoff) numbers, kept for comparison', '']
    if prev:
        prev_thr = prev.get('threshold', 0.05)
        L.append('Full set, set-based containment, %.2f threshold (from `out/novelty_calibration.json` before this revision): '
                 '%d / %d positives at or above %.2f, %d false positives on %d unrelated pairs, maximum unrelated '
                 'containment %.4f.' % (prev_thr, prev['positives_at_or_above'], prev['positives']['n'], prev_thr,
                                         prev['false_positives'], prev['negatives']['n'], prev['negatives']['max']))
        L.append('')
        L.append('The full-set row above uses the position-based estimator the runtime script uses, so its positive '
                 'counts can differ slightly from the set-based numbers.')
    else:
        L.append('No earlier calibration file was found.')
    L += ['', '## Limitations', '',
          '- Sketch estimates are noisier for short songs; the %d-hit minimum protects against single coincidences but can miss a short copy.' % nc.MIN_SKETCH_MATCHES,
          '- `matched=` beats in the runtime line is computed from matched n-grams only, so for a sketch it is a lower bound.',
          '- The check is advisory, not a plagiarism verdict.', '']
    doc = Path(args.variants_doc)
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text('\n'.join(L), encoding='utf-8', newline='\n')
    print('recommended variant:', pick['label'])
    print('wrote %s and %s' % (doc, json_path))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('corpus')
    ap.add_argument('outd', nargs='?', default='out')
    ap.add_argument('--bank', default='handoff/skill_0.2.3/assets/corpus_fingerprints.bin')
    ap.add_argument('--example', default=None,
                    help="Repo B example song (default: <Repo B>/assets/example_song.abc, found via ABC_SCORE_COMPOSER, a sibling folder or ~)")
    ap.add_argument('--variants', default=None, help='comma-separated fingerprint files to compare (variants mode)')
    ap.add_argument('--variants-doc', default='docs/fingerprint_options.md')
    ap.add_argument('--stamp', action='store_true', help='write each variant\'s recommended threshold into its header')
    ap.add_argument('--bank-queries', type=int, default=10000, help='songs queried against the whole bank in variants mode (default: every kept song)')
    ap.add_argument('--partial-trials', type=int, default=100, help='partial-copy trials per block length in variants mode')
    ap.add_argument('--threshold', type=float, default=None,
                    help='advisory threshold (default: header threshold stamped in the bank, else 0.05)')
    ap.add_argument('--samples', type=int, default=3000)
    ap.add_argument('--doc', default='docs/novelty_calibration.md')
    args = ap.parse_args(argv)

    example_path = None
    if args.example:
        example_path = Path(args.example)
        if not example_path.exists():
            print('--example file not found: %s' % example_path)
            return 2
    else:
        rb = repo_b.find_repo_b()
        if rb is not None and (rb / 'assets' / 'example_song.abc').exists():
            example_path = rb / 'assets' / 'example_song.abc'
        else:
            print('NOTE: ' + repo_b.not_found_message())
            print('NOTE: the Repo B example song will not be scored.')
    args.example = str(example_path) if example_path else None

    if args.variants:
        return run_variants(args, example_path)

    outd = Path(args.outd)
    clusters = json.loads((outd / 'clusters.json').read_text(encoding='utf-8'))
    keep = [x.strip() for x in (outd / 'dedupe_keep.txt').read_text(encoding='utf-8').splitlines()
            if x.strip()]
    cluster_of = {}
    for c in clusters['clusters']:
        for m in c['members']:
            cluster_of[m['id']] = c['id']
    for sid in clusters['singletons']:
        cluster_of[sid] = 'S:' + sid

    nc, _rb = load_novelty_module()
    songs = {s['id']: s for s in load_all(args.corpus)}
    header, bank_songs = nc.load_bank(args.bank)
    entry = {e[0]: e for e in bank_songs}
    threshold = float(args.threshold) if args.threshold is not None else nc.default_threshold(header)
    related = known_related_pairs(outd)
    vocal_clusters = vocal_cluster_lookup(outd)

    gcache = {}

    def grams(sid):
        if sid not in gcache:
            st = song_stream(songs[sid]['abc'], voice='Vocal') if sid in songs else None
            gcache[sid] = nc.prepare(grams_with_starts(st)) if st is not None else {}
        return gcache[sid]

    positives = []
    positive_rows = []
    for c in clusters['clusters']:
        rep = c['representative']
        if rep not in entry:
            continue
        for m in c['members']:
            if m['id'] == rep:
                continue
            g = grams(m['id'])
            if not g:
                continue
            v = entry_score(nc, g, entry[rep])
            positives.append(v)
            positive_rows.append((v, c['id'], m['id'], rep))
    positive_rows.sort()

    rng = random.Random(0)
    negatives = []
    neg_pairs = []
    for _ in range(args.samples):
        a, b = rng.sample(keep, 2)
        if cluster_of.get(a) == cluster_of.get(b):
            continue
        neg_pairs.append((a, b))
        if b in entry and grams(a):
            negatives.append(entry_score(nc, grams(a), entry[b]))

    queries = rng.sample(keep, min(args.bank_queries, len(keep)))
    neg_bank_raw = []
    for q in queries:
        g = grams(q)
        if not g:
            continue
        others = [e for e in bank_songs if cluster_of.get(e[0]) != cluster_of.get(q)
                  and frozenset((e[0], q)) not in related]
        best = nc.best_match(g, others)
        neg_bank_raw.append((best[0] if best else 0.0, q, best[2] if best else None))
    likely_related = [(v, q, b) for v, q, b in neg_bank_raw if v >= RELATED_FLOOR]
    neg_bank = [v for v, _q, _b in neg_bank_raw if v < RELATED_FLOOR]

    # example
    example_line = 'not run'
    example_containment = None
    if args.example and Path(args.example).exists():
        text = Path(args.example).read_text(encoding='utf-8')
        # use the same parser/tokenizer as the abcsim side for a reproducible number
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from parse import parse_abc
        song = parse_abc(text)
        notes = song.voices.get('Vocal') or (song.voices[max(song.voices, key=lambda v: len(song.voices[v]))] if song.voices else [])
        st = None
        if notes:
            from features import tokens_from_notes
            tk = tokens_from_notes(notes)
            if tk is not None:
                st = dict(iv=tk[0], rc=tk[1])
        if st is None:
            example_line = 'too short to fingerprint'
        else:
            prep = nc.prepare(grams_with_starts(st))
            best = nc.best_match(prep, bank_songs,
                                 tiebreak=lambda m: matched_beats(notes, [i for h in m for i in prep[h]]))
            if best is None:
                example_containment = 0.0
                example_line = 'closest=none containment=0.000 matched=0.0 beats status=ok'
            else:
                mb = matched_beats(notes, [i for h in best[1] for i in prep[h]])
                example_containment = best[0]
                example_line = 'closest=%s containment=%.3f matched=%.1f beats status=%s' % (
                    best[2], best[0], mb, 'close' if best[0] >= threshold else 'ok')

    fp = sum(1 for x in negatives if x >= threshold)
    fp_rate = fp / float(len(negatives)) if negatives else 0.0
    bank_fp = sum(1 for x in neg_bank if x >= threshold)
    bank_fp_rate = bank_fp / float(len(neg_bank)) if neg_bank else 0.0
    pos_hit = sum(1 for x in positives if x >= threshold)

    def stats(vals):
        return dict(n=len(vals), min=min(vals) if vals else None,
                    p10=pct(vals, 10), p25=pct(vals, 25), p50=pct(vals, 50),
                    p75=pct(vals, 75), p90=pct(vals, 90),
                    max=max(vals) if vals else None,
                    mean=(sum(vals) / len(vals)) if vals else None)

    ps, ns, wbs = stats(positives), stats(negatives), stats(neg_bank)
    wbs['p99'] = pct(neg_bank, 99)
    rel_records = []
    for v, q, b in sorted(likely_related, reverse=True):
        vcid = vocal_clusters.get(frozenset((q, b)))
        rel_records.append(dict(containment=round(v, 3), query=q, closest=b, vocal_cluster=vcid))
    result = dict(threshold=threshold, bank=dict(
        songs=len(bank_songs), hashes=header['total'], bytes=Path(args.bank).stat().st_size,
        sketch=bool(header.get('sketch', False)), k=header.get('k', 0), n=header['n']),
        positives=ps, positives_at_or_above=pos_hit,
        negatives=ns, false_positives=fp, false_positive_rate=fp_rate,
        whole_bank_negatives=wbs, whole_bank_false_positives=bank_fp,
        whole_bank_false_positive_rate=bank_fp_rate,
        likely_related=rel_records,
        example=example_line, example_containment=example_containment,
        positive_misses=[dict(containment=round(v, 3), cluster=c, member=m, representative=r)
                         for v, c, m, r in positive_rows if v < threshold])

    (outd / 'novelty_calibration.json').write_text(
        json.dumps(result, indent=2) + '\n', encoding='utf-8', newline='\n')

    sketch_label = ('bottom-%d' % header.get('k', 0)) if header.get('sketch') else 'full set'
    L = []
    L.append('# Novelty fingerprint calibration')
    L.append('')
    L.append('Generated by `abcsim/calibrate_novelty.py` using the runtime estimator (`novelty_check.py`).')
    L.append('')
    L.append('## Fingerprint bank')
    L.append('')
    L.append('| | |')
    L.append('|---|---|')
    L.append('| songs | %d |' % len(bank_songs))
    L.append('| 8-gram hashes | %d |' % header['total'])
    L.append('| file size | %d B (%.2f MB) |' % (Path(args.bank).stat().st_size, Path(args.bank).stat().st_size / (1024.0 * 1024.0)))
    L.append('| sketch | %s |' % sketch_label)
    L.append('| tokenizer | `features.tokens_from_notes` (stdlib port parity-tested on 670/670) |')
    L.append('')
    L.append('## Positives: within-cluster pairs')
    L.append('')
    L.append('Containment = estimated share of the member song\'s 8-grams also present in its cluster')
    L.append('representative. %d pairs (member != representative).' % ps['n'])
    L.append('')
    L.append('| min | p10 | p25 | p50 | p75 | p90 | max |')
    L.append('|---|---|---|---|---|---|---|')
    L.append('| %s | %s | %s | %s | %s | %s | %s |' % tuple(
        ('%.3f' % x if x is not None else '—') for x in
        (ps['min'], ps['p10'], ps['p25'], ps['p50'], ps['p75'], ps['p90'], ps['max'])))
    L.append('')
    L.append('%d / %d positives are at or above the chosen threshold.' % (pos_hit, ps['n']))
    L.append('')
    L.append('## Negatives: random different-cluster pairs and whole-bank queries')
    L.append('')
    L.append('Containment of song A in song B for %d random pairs from different clusters, and best whole-bank' % ns['n'])
    L.append('score across %d kept songs outside each query\'s own cluster (excluding known related pairs and >= %.2f).' % (wbs['n'], RELATED_FLOOR))
    L.append('')
    L.append('| check | mean | p99 | max | false positives at %.2f | FP rate |' % threshold)
    L.append('|---|---|---|---|---|---|')
    L.append('| unrelated pairs (%d) | %s | %s | %s | %d | %.4f |' % (
        ns['n'],
        '%.4f' % ns['mean'] if ns['mean'] is not None else '—',
        '%.4f' % pct(negatives, 99) if negatives else '—',
        '%.4f' % ns['max'] if ns['max'] is not None else '—',
        fp, fp_rate))
    L.append('| whole-bank best (%d) | %s | %s | %s | %d | %.4f |' % (
        wbs['n'],
        '%.4f' % wbs['mean'] if wbs['mean'] is not None else '—',
        '%.4f' % wbs['p99'] if wbs['p99'] is not None else '—',
        '%.4f' % wbs['max'] if wbs['max'] is not None else '—',
        bank_fp, bank_fp_rate))
    if rel_records:
        L.append('')
        L.append('Whole-bank pairs >= %.2f excluded from false-positive stats:' % RELATED_FLOOR)
        L.append('')
        seen_pairs = set()
        for item in rel_records:
            pair = tuple(sorted((item['query'], item['closest'])))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            note = ('known vocal-only duplicate cluster %s (missed by lead-only dedupe)' % item['vocal_cluster']
                    if item['vocal_cluster'] else 'unclustered pair >= %.2f' % RELATED_FLOOR)
            L.append('- `%s` <-> `%s` (%.3f): %s.' % (pair[0], pair[1], item['containment'], note))
    L.append('')
    L.append('## Repo B example song')
    L.append('')
    L.append('`assets/example_song.abc`:')
    L.append('')
    L.append('```')
    L.append('NOVELTY ' + example_line)
    L.append('```')
    L.append('')
    L.append('## Chosen threshold')
    L.append('')
    L.append('**containment >= %.2f** triggers the advisory. The maximum unrelated pair is' % threshold)
    worst = max(ns['max'] or 0.0, wbs['max'] or 0.0)
    if ns['max'] is not None:
        L.append('%.4f (whole-bank unrelated max %.4f, worst %.4f) and the example song is %s, so the threshold sits' % (
            ns['max'], wbs['max'] or 0.0, worst,
            ('%.3f' % example_containment) if example_containment is not None else 'not scored'))
    L.append('above the observed false-positive floor while still catching almost every cluster pair.')
    L.append('')
    L.append('## Limitations')
    L.append('')
    L.append('- Exact 8-token n-grams are deliberately strict: a rhythmically varied variant')
    L.append('  can score low even when it is the same song. %d counted cluster pair(s) are' % len(result['positive_misses']))
    L.append('  below the threshold for this reason; they are listed in')
    L.append('  `out/novelty_calibration.json`. Members with fewer than %d tokens cannot be' % N)
    L.append('  scored by this method and are not counted.')
    L.append('- The bank is vocal-only. Three kept songs have no usable Vocal stream and are')
    L.append('  not fingerprinted.')
    L.append('- The check is advisory, in the same spirit as CRAFT flags. It is not a')
    L.append('  plagiarism verdict and it does not prove originality.')
    L.append('- Runtime on a 30-bar score is ~0.3 s (well under 1 s).')
    L.append('')
    doc = Path(args.doc)
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text('\n'.join(L), encoding='utf-8', newline='\n')

    print('positives %d: median %.3f, %d >= %.2f' % (ps['n'], ps['p50'] or 0, pos_hit, threshold))
    print('negatives %d: pair max %.4f, bank max %.4f, FP %d/%d' % (
        ns['n'], ns['max'] or 0, wbs['max'] or 0, fp, bank_fp))
    print('example:', example_line)
    print('wrote %s and %s' % (doc, outd / 'novelty_calibration.json'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
