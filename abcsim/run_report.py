"""run_report.py -- turn raw alignment scores into: calibrated z-scores, top pairs with the matching bars, and ground-truth checks.
Outputs: out/top_pairs.csv, out/groundtruth.txt, out/null_hist.png"""
import sys, os, pickle, csv, difflib, re, collections
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
from stats import null_model

outd = sys.argv[1] if len(sys.argv) > 1 else 'out'; os.makedirs(outd, exist_ok=True)
idx = pickle.load(open(os.path.join(outd, 'index.pkl'), 'rb'))
d = np.load(os.path.join(outd, 'pairs_raw.npz')); pairs = d['pairs']; res = d['res']
meta = idx['meta']; offs = idx['offs']; n = len(meta)
score = res[:, 0].astype(np.float64)
coef, sig, z = null_model(idx, pairs, res)
print('null model: score = %.2f + %.2f*log(nA*nB); robust sigma %.2f' % (coef[0], coef[1], sig))
print('median score of unrelated-looking pairs: %.1f ; 99th pct %.1f ; 99.99th pct %.1f' % (
    np.median(score), np.percentile(score, 99), np.percentile(score, 99.99)))


def seg_info(k):
    a, b = pairs[k]
    sA, eA, sB, eB = [int(v) for v in res[k, 1:5]]
    def one(i, s, e):
        on = idx['onsets'][i]; br = idx['bars'][i]
        e2 = min(e + 2, len(on) - 1)
        beats = float(on[e2] - on[s]); return int(br[s]) + 1, int(br[e2]) + 1, beats, e - s + 1
    return one(a, sA, eA), one(b, sB, eB), (a, sA, eA), (b, sB, eB)


def triviality(i, s, e):
    iv = idx['ivs'][offs[i] + s: offs[i] + e + 1]; rc = idx['rcs'][offs[i] + s: offs[i] + e + 1]
    same = np.mean((iv == 0) & (rc == 0)) if len(iv) else 1
    return round(float(same), 2), len({(int(p), int(q)) for p, q in zip(iv, rc)})


def stem(s):
    s = s.split('/')[-1]; s = re.sub(r'_\d{6,}$', '', s); return s.replace('3', 'a').replace('_', '')


# ---- known relations (independent of the alignment) ------------------------------------------
rel = {}
ids = [m['id'] for m in meta]
gen = [i for i, m in enumerate(meta) if m['corpus'] == 'GEN']
sel = [i for i, m in enumerate(meta) if m['corpus'] == 'SEL']
for g in gen:
    sc = [(difflib.SequenceMatcher(None, stem(meta[g]['id']), stem(meta[s]['id'])).ratio(), s) for s in sel]
    r, s = max(sc)
    if r >= 0.7: rel[frozenset((g, s))] = 'generated-conditioner<->selected-transcription (name match %.2f)' % r
grp = collections.defaultdict(list)
for i, m in enumerate(meta):
    if m['dup']: grp[m['dup']].append(i)
for g, l in grp.items():
    for a in l:
        for b in l:
            if a < b: rel[frozenset((a, b))] = 'YT500 duplicate group'

pidx = {(int(a), int(b)): k for k, (a, b) in enumerate(pairs)}
rank_all = np.argsort(-z)
position = np.empty(len(z), np.int64); position[rank_all] = np.arange(len(z))

# ---- ground truth check ----------------------------------------------------------------------
lines = []
lines.append('KNOWN RELATED PAIRS (from names / duplicate groups), and where the alignment ranked them among %d pairs' % len(z))
nbr = collections.defaultdict(list)
for k, (a, b) in enumerate(pairs):
    nbr[a].append((z[k], b)); nbr[b].append((z[k], a))
top1 = 0; tot = 0
for fs, why in rel.items():
    a, b = sorted(fs); k = pidx[(a, b)]
    best_for_a = max(nbr[a])[1]; best_for_b = max(nbr[b])[1]
    hit = (best_for_a == b) or (best_for_b == b) or (best_for_a == a) or (best_for_b == a)
    tot += 1; top1 += (best_for_a == b) and (best_for_b == a)
    lines.append('%-62s z=%6.1f  rank=%5d  mutual-nearest=%s  | %s' % (
        (meta[a]['id'][-28:] + ' ~ ' + meta[b]['id'][-28:]), z[k], position[k] + 1,
        (best_for_a == b) and (best_for_b == a), why[:40]))
lines.append('mutual nearest neighbours: %d / %d known pairs' % (top1, tot))
open(os.path.join(outd, 'groundtruth.txt'), 'w').write('\n'.join(lines))
print('\n'.join(lines[:1] + lines[-1:]))

# ---- top pairs ------------------------------------------------------------------------------
rows = []
for k in rank_all[:300]:
    a, b = pairs[k]
    (a0, a1, ab, an), (b0, b1, bb, bn), sa, sb = seg_info(k)
    triv, distinct = triviality(a, sa[1], sa[2])
    tempo = meta[a]['tempo']
    rows.append(dict(rank=len(rows) + 1, z=round(float(z[k]), 1), raw_score=round(float(score[k]), 1),
                     song_A=meta[a]['title'] if meta[a]['corpus'] in ('SEL', 'GEN') else meta[a]['artist'] + ' | ' + str(meta[a]['title']),
                     id_A=meta[a]['id'], bars_A='%d-%d' % (a0, a1), song_B=meta[b]['title'] if meta[b]['corpus'] in ('SEL', 'GEN') else meta[b]['artist'] + ' | ' + str(meta[b]['title']),
                     id_B=meta[b]['id'], bars_B='%d-%d' % (b0, b1), matched_tokens=an, matched_beats=round(ab, 1),
                     approx_seconds=round(ab * 60 / tempo, 1), trivial_fraction=triv, distinct_tokens=distinct,
                     known_relation=rel.get(frozenset((int(a), int(b))), '')))
with open(os.path.join(outd, 'top_pairs.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator='\n'); w.writeheader(); w.writerows(rows)

unk = [r for r in rows if not r['known_relation']]
print('\nTOP UNKNOWN-RELATION PAIRS')
for r in unk[:15]:
    print('%3d z=%5.1f beats=%5.1f ~%4.0fs tok=%3d  %s [%s]  ~  %s [%s]' % (r['rank'], r['z'], r['matched_beats'], r['approx_seconds'], r['matched_tokens'],
          r['song_A'][:38], r['bars_A'], r['song_B'][:38], r['bars_B']))
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
plt.figure(figsize=(7, 4)); plt.hist(z, bins=200, color='#999', log=True)
for fs in rel:
    a, b = sorted(fs); plt.axvline(z[pidx[(a, b)]], color='crimson', alpha=.35, lw=1)
plt.xlabel('z (alignment score vs. unrelated pairs)'); plt.ylabel('pairs (log)'); plt.title('Null distribution of %d pairs; red = known same-song pairs' % len(z))
plt.tight_layout(); plt.savefig(os.path.join(outd, 'null_hist.png'), dpi=130)
