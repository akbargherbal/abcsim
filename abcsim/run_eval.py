"""run_eval.py -- how short an excerpt can the method find, and how much noise can it take?
We cut an excerpt of L bars out of a song, damage it (dropped / inserted / wrong notes, timing jitter, octave slips),
and ask: is the true song the best match among all 670?   Output: out/eval_excerpt.csv, out/eval_excerpt.png"""
import sys, os, pickle, csv, random
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
from corpus import load_all
from parse import parse_abc, lead_voice
from features import tokens_from_notes
from align import sw_many, GAP, MISMATCH

root = sys.argv[1]; outd = sys.argv[2] if len(sys.argv) > 2 else 'out'; os.makedirs(outd, exist_ok=True)
idx = pickle.load(open(os.path.join(outd, 'index.pkl'), 'rb'))
meta = idx['meta']; offs = idx['offs']; W = idx['W']; n = len(meta)
rng = random.Random(7); nrng = np.random.default_rng(7)
songs = {s['id']: s for s in load_all(root)}
cand = [i for i, m in enumerate(meta) if m['corpus'] == 'YT500' and not m['dup']] or [i for i, m in enumerate(meta) if not m['dup']]
picked = rng.sample(cand, min(60, len(cand)))
NOISE = {'clean': dict(drop=0, ins=0, pit=0, tim=0, octv=0),
         'moderate': dict(drop=.05, ins=.05, pit=.05, tim=.10, octv=.01),
         'heavy': dict(drop=.15, ins=.10, pit=.15, tim=.20, octv=.03)}
LENS = [1, 2, 3, 4, 6, 8, 12, 16]


def damage(on, pi, cfg):
    on = list(on); pi = list(pi); o2 = []; p2 = []
    for t, p in zip(on, pi):
        if nrng.random() < cfg['drop']: continue
        if nrng.random() < cfg['pit']: p += int(nrng.choice([-2, -1, 1, 2]))
        if nrng.random() < cfg['octv']: p += int(nrng.choice([-12, 12]))
        o2.append(t); p2.append(p)
        if nrng.random() < cfg['ins']:
            o2.append(t + 0.5 * 0.25); p2.append(p + int(nrng.choice([-2, -1, 1, 2])))
    o2 = np.array(o2); p2 = np.array(p2)
    if len(o2) < 4: return None
    ioi = np.diff(o2); o2 = np.concatenate([[o2[0]], o2[0] + np.cumsum(ioi * (1 + nrng.normal(0, cfg['tim'], len(ioi))))])
    return o2, p2


class N:  # minimal Note-like
    def __init__(s, o, p): s.onset = o; s.midi = p


rows = []
shift_k = 5; tempo_scale = 2.0     # every query is also transposed +5 semitones and played at double length
for ci, i in enumerate(picked):
    ps = parse_abc(songs[meta[i]['id']]['abc']); v = meta[i]['voice']; notes = ps.voices[v]
    on = np.array([x.onset for x in notes]); pi = np.array([x.midi for x in notes])
    for L in LENS:
        # an excerpt of L bars (4/4-equivalent = 4L beats) that contains plenty of notes
        for tries in range(30):
            t0 = rng.choice(on[: max(1, len(on) - 4 * L)]) if len(on) > 4 else 0
            sel = (on >= t0) & (on < t0 + 4 * L)
            if sel.sum() >= max(4, 2 * L): break
        else:
            continue
        for nz, cfg in NOISE.items():
            dm = damage(on[sel] * tempo_scale, pi[sel] + shift_k, cfg)
            if dm is None: continue
            tk = tokens_from_notes([N(a, b) for a, b in zip(*dm)])
            if tk is None: continue
            iv, rc = tk
            w = W[(iv.astype(np.int32) + 12) * 9 + (rc.astype(np.int32) + 4)].astype(np.float32)
            # query = song index n (appended), compare against all songs via a tiny local concat
            ivs = np.concatenate([idx['ivs'], iv]); rcs = np.concatenate([idx['rcs'], rc])
            ws = np.concatenate([idx['ws'], w]); offs2 = np.concatenate([offs, [offs[-1] + len(iv)]])
            pr = np.array([[n, j] for j in range(n)], np.int64)
            sc = sw_many(ivs, rcs, ws, offs2, pr, GAP, MISMATCH)[:, 0]
            order = np.argsort(-sc); rank = int(np.where(order == i)[0][0]) + 1
            # a different song only counts as 'the wrong winner' if it is not a known duplicate of the source
            rows.append(dict(song=meta[i]['id'], bars=L, noise=nz, tokens=len(iv), rank=rank, top1=int(rank == 1),
                             true_score=float(sc[i]), best_other=float(np.max(np.delete(sc, i)))))
    if ci % 10 == 0: print('queries from', ci + 1, '/', len(picked), 'songs', flush=True)
with open(os.path.join(outd, 'eval_excerpt.csv'), 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print('\nTop-1 accuracy (true song ranked first of %d), query transposed +5 and at double tempo:' % n)
print('bars   ' + '   '.join('%9s' % k for k in NOISE))
curve = {k: [] for k in NOISE}
for L in LENS:
    cells = []
    for nz in NOISE:
        r = [x['top1'] for x in rows if x['bars'] == L and x['noise'] == nz]
        acc = np.mean(r) if r else float('nan'); curve[nz].append(acc); cells.append('%8.0f%%' % (100 * acc))
    toks = np.median([x['tokens'] for x in rows if x['bars'] == L])
    print('%4d   %s   (median %d notes)' % (L, '   '.join(cells), toks + 2))
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
plt.figure(figsize=(7, 4.2))
for nz, c in zip(NOISE, ['#2a9d8f', '#e9a23b', '#c8553d']): plt.plot(LENS, [100 * v for v in curve[nz]], 'o-', label=nz, color=c)
plt.axvline(6, ls='--', color='gray'); plt.text(6.1, 8, '"6 bars"', color='gray')
plt.xlabel('excerpt length (bars)'); plt.ylabel('%% found as best match among %d songs' % n); plt.legend(title='noise')
plt.title('How short a melody can be found?'); plt.grid(alpha=.3); plt.tight_layout(); plt.savefig(os.path.join(outd, 'eval_excerpt.png'), dpi=130)
