"""compare_bands.py -- compare Repo B's corpus profile on the full vs deduped set.

Reads out/profile_full.json and out/profile_dedup.json (both produced by Repo B's
scripts/mine_corpus.py) and writes out/bands_shift.md.

The decision rule is the plan's: a metric matters only if a percentile moves by
more than 10% of the full-corpus IQR (p75 - p25).  The deduped profile is also
copied to the handoff folder as a *candidate*, labelled as such; the
recommendation in the report decides whether a human should adopt it.

Usage:
    python abcsim/compare_bands.py out
"""
import argparse
import json
import shutil
from pathlib import Path

PCTS = ['p10', 'p25', 'p50', 'p75', 'p90']
THRESHOLD = 10.0


def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def fmt(x):
    if x is None:
        return '—'
    if isinstance(x, int):
        return str(x)
    if abs(x) >= 100:
        return '%.1f' % x
    if abs(x) >= 1:
        return '%.3f' % x
    return '%.4f' % x


def metric_rows(full, dedup):
    rows = []
    for name in full['percentiles']:
        a = full['percentiles'][name]
        b = dedup['percentiles'].get(name, {})
        iqr = (a.get('p75', 0) - a.get('p25', 0)) if a.get('p75') is not None else None
        max_shift = 0.0
        for pct in PCTS:
            av, bv = a.get(pct), b.get(pct)
            if av is None or bv is None:
                rows.append(dict(metric=name, pct=pct, full=av, dedup=bv,
                                 shift=None, iqr=iqr, pct_iqr=None, flag=False))
                continue
            shift = bv - av
            pct_iqr = abs(shift) / iqr * 100.0 if iqr else (0.0 if shift == 0 else float('inf'))
            max_shift = max(max_shift, pct_iqr)
            rows.append(dict(metric=name, pct=pct, full=av, dedup=bv,
                             shift=shift, iqr=iqr, pct_iqr=pct_iqr,
                             flag=pct_iqr > THRESHOLD))
        rows[-1]['max_shift'] = max_shift
    return rows


def ranks(items):
    return {x: i + 1 for i, x in enumerate(items)}


def form_table(full, dedup):
    fa = full['sections']['forms']
    fb = dedup['sections']['forms']
    ca = {r['form']: r['count'] for r in fa}
    cb = {r['form']: r['count'] for r in fb}
    order_a = [r['form'] for r in fa]
    order_b = [r['form'] for r in fb]
    ra, rb = ranks(order_a), ranks(order_b)
    chosen = order_a[:15]
    for f in order_b[:10]:
        if f not in chosen:
            chosen.append(f)
    rows = []
    for f in chosen:
        rows.append(dict(form=f, full=ca.get(f, 0), dedup=cb.get(f, 0),
                         delta=cb.get(f, 0) - ca.get(f, 0),
                         rank_full=ra.get(f), rank_dedup=rb.get(f)))
    return rows


def chord_table(full, dedup, which):
    if which == 'qualities':
        ca = full['chords']['qualities']
        cb = dedup['chords']['qualities']
        order_a = list(ca)
        order_b = list(cb)
    else:
        ca = {tuple(x['loop']): x['count'] for x in full['chords']['loops']}
        cb = {tuple(x['loop']): x['count'] for x in dedup['chords']['loops']}
        order_a = list(ca)
        order_b = list(cb)
    ra, rb = ranks(order_a), ranks(order_b)
    chosen = order_a[:20]
    for k in order_b[:15]:
        if k not in chosen:
            chosen.append(k)
    rows = []
    for k in chosen:
        rows.append(dict(item=k, full=ca.get(k, 0), dedup=cb.get(k, 0),
                         delta=cb.get(k, 0) - ca.get(k, 0),
                         rank_full=ra.get(k), rank_dedup=rb.get(k)))
    return rows


def key_table(full, dedup):
    ca, cb = full['keys'], dedup['keys']
    order_a, order_b = list(ca), list(cb)
    ra, rb = ranks(order_a), ranks(order_b)
    ta, tb = sum(ca.values()), sum(cb.values())
    chosen = order_a[:20]
    for k in order_b[:15]:
        if k not in chosen:
            chosen.append(k)
    rows = []
    for k in chosen:
        a, b = ca.get(k, 0), cb.get(k, 0)
        rows.append(dict(key=k, full=a, dedup=b, delta=b - a,
                         pct_full=100.0 * a / ta if ta else 0.0,
                         pct_dedup=100.0 * b / tb if tb else 0.0,
                         rank_full=ra.get(k), rank_dedup=rb.get(k)))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('outd', nargs='?', default='out')
    ap.add_argument('--full', help='default: OUTD/profile_full.json')
    ap.add_argument('--dedup', help='default: OUTD/profile_dedup.json')
    ap.add_argument('--handoff', default='handoff/skill_0.2.3',
                    help='where to put the candidate profile (default: %(default)s)')
    args = ap.parse_args(argv)

    outd = Path(args.outd)
    full = load(args.full or outd / 'profile_full.json')
    dedup = load(args.dedup or outd / 'profile_dedup.json')
    rows = metric_rows(full, dedup)
    worst = max((r['max_shift'] for r in rows if r.get('max_shift') is not None), default=0.0)
    adopt = worst > THRESHOLD

    L = []
    L.append('# Corpus bands: full vs deduped')
    L.append('')
    L.append('Generated by `abcsim/compare_bands.py` from Repo B `v0.2.2`')
    L.append('`scripts/mine_corpus.py` outputs.')
    L.append('')
    L.append('| | full | deduped |')
    L.append('|---|---|---|')
    L.append('| files | %d | %d |' % (full['corpus']['files'], dedup['corpus']['files']))
    L.append('| used for vocal | %d | %d |' % (full['corpus']['used_for_vocal'],
                                               dedup['corpus']['used_for_vocal']))
    L.append('| empty vocal | %d | %d |' % (full['corpus']['empty_vocal_count'],
                                            dedup['corpus']['empty_vocal_count']))
    L.append('| glitch bars | %d | %d |' % (full['corpus']['glitch_count'],
                                            dedup['corpus']['glitch_count']))
    L.append('')
    L.append('**Decision rule:** a percentile shift matters when it exceeds **%g%% of the' % THRESHOLD)
    L.append('full-corpus IQR** (p75 - p25).')
    L.append('')
    L.append('## Recommendation')
    L.append('')
    if adopt:
        L.append('**Adopt the deduped profile.** The largest shift is %.1f%% of the IQR, above' % worst)
        L.append('the %g%% threshold. Use `assets/corpus_profile.dedup.candidate.json`.' % THRESHOLD)
    else:
        L.append('**Keep the current profile.** The largest shift is %.1f%% of the IQR, well' % worst)
        L.append('below the %g%% threshold. Deduping changes counts, not the bands the skill' % THRESHOLD)
        L.append('uses. The deduped profile is still included as a *candidate* for inspection,')
        L.append('but adopting it is not necessary.')
    L.append('')
    L.append('## Percentile bands')
    L.append('')
    L.append('| metric | pct | full | deduped | shift | IQR (full) | shift %% IQR | >%g%%? |' % THRESHOLD)
    L.append('|---|---|---|---|---|---|---|---|')
    for r in rows:
        flag = '**yes**' if r['flag'] else ''
        L.append('| %s | %s | %s | %s | %s | %s | %s | %s |' % (
            r['metric'], r['pct'], fmt(r['full']), fmt(r['dedup']),
            fmt(r['shift']), fmt(r['iqr']),
            ('—' if r['pct_iqr'] is None else ('inf' if r['pct_iqr'] == float('inf') else '%.1f%%' % r['pct_iqr'])),
            flag))
    L.append('')
    L.append('### Largest shift per metric')
    L.append('')
    L.append('| metric | max shift %% IQR | >%g%%? |' % THRESHOLD)
    L.append('|---|---|---|')
    per_metric = {}
    for r in rows:
        if r.get('max_shift') is not None:
            per_metric[r['metric']] = r['max_shift']
    for name, val in sorted(per_metric.items(), key=lambda kv: -kv[1]):
        L.append('| %s | %.1f%% | %s |' % (name, val, '**yes**' if val > THRESHOLD else ''))
    L.append('')
    L.append('## Forms (top section orders)')
    L.append('')
    L.append('| form | full | deduped | delta | rank full | rank deduped |')
    L.append('|---|---|---|---|---|---|')
    for r in form_table(full, dedup):
        L.append('| %s | %d | %d | %+d | %s | %s |' % (
            r['form'], r['full'], r['dedup'], r['delta'],
            r['rank_full'] or '—', r['rank_dedup'] or '—'))
    L.append('')
    L.append('## Chord qualities')
    L.append('')
    L.append('| quality | full | deduped | delta | rank full | rank deduped |')
    L.append('|---|---|---|---|---|---|')
    for r in chord_table(full, dedup, 'qualities'):
        L.append('| %s | %d | %d | %+d | %s | %s |' % (
            r['item'], r['full'], r['dedup'], r['delta'],
            r['rank_full'] or '—', r['rank_dedup'] or '—'))
    L.append('')
    L.append('## Chord loops')
    L.append('')
    L.append('| loop | full | deduped | delta | rank full | rank deduped |')
    L.append('|---|---|---|---|---|---|')
    for r in chord_table(full, dedup, 'loops'):
        L.append('| %s | %d | %d | %+d | %s | %s |' % (
            ' '.join(r['item']), r['full'], r['dedup'], r['delta'],
            r['rank_full'] or '—', r['rank_dedup'] or '—'))
    L.append('')
    L.append('## Key distribution')
    L.append('')
    L.append('| key | full | deduped | full % | dedup % | delta | rank full | rank deduped |')
    L.append('|---|---|---|---|---|---|---|---|')
    for r in key_table(full, dedup):
        L.append('| %s | %d | %d | %.1f%% | %.1f%% | %+d | %s | %s |' % (
            r['key'], r['full'], r['dedup'], r['pct_full'], r['pct_dedup'],
            r['delta'], r['rank_full'] or '—', r['rank_dedup'] or '—'))
    L.append('')
    L.append('## Notes')
    L.append('')
    L.append('- Counts (forms, chords, keys) always change slightly because 71 files are')
    L.append('  removed; what matters for the skill is whether the percentile bands move.')
    L.append('- The deduped profile is a candidate, not an adopted asset. Repo B is not')
    L.append('  modified by this repository.')
    L.append('')

    out = outd / 'bands_shift.md'
    out.write_text('\n'.join(L), encoding='utf-8', newline='\n')

    # candidate profile in the handoff folder (clearly named as a candidate)
    handoff_assets = Path(args.handoff) / 'assets'
    handoff_assets.mkdir(parents=True, exist_ok=True)
    cand = handoff_assets / 'corpus_profile.dedup.candidate.json'
    shutil.copyfile(args.dedup or outd / 'profile_dedup.json', cand)

    print('largest shift: %.1f%% of IQR -> %s' % (worst, 'ADOPT' if adopt else 'KEEP CURRENT'))
    print('wrote %s' % out)
    print('wrote %s' % cand)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
