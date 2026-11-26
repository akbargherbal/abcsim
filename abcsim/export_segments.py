"""export_segments.py -- write the matched passages of the top candidate pairs as MIDI so you can LISTEN to them.
Each file = passage from song A, 2 s pause, passage from song B (B moved to A's key, stretched to A's length)."""
import sys, os, csv, pickle
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, mido
from corpus import load_all
from parse import parse_abc

argv = sys.argv[1:]
root, outd = argv[0], argv[1]
os.makedirs(outd, exist_ok=True)
topn = 8; pairs_file = None; tag = ''
i = 2
while i < len(argv):
    a = argv[i]
    if a == '--pairs':
        pairs_file = argv[i + 1]; i += 2
    elif a == '--tag':
        tag = argv[i + 1]; i += 2
    elif a == '--topn':
        topn = int(argv[i + 1]); i += 2
    else:
        topn = int(a); i += 1
idx = pickle.load(open(os.path.join(outd, 'index.pkl'), 'rb')); meta = idx['meta']
d = np.load(os.path.join(outd, 'pairs_raw.npz')); pairs = d['pairs']; res = d['res']
pid = {(int(a), int(b)): k for k, (a, b) in enumerate(pairs)}
byid = {m['id']: i for i, m in enumerate(meta)}
songs = {s['id']: s for s in load_all(root)}
explicit = pairs_file is not None
if explicit:
    # one "idA idB" (tab/comma/space separated) per line; no top-pairs filtering
    rows = []
    with open(pairs_file, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            p = [x for x in line.replace(',', ' ').replace('\t', ' ').split() if x]
            if len(p) >= 2:
                r = dict(id_A=p[0], id_B=p[1], known_relation='',
                         raw_score='', trivial_fraction='0', distinct_tokens='99')
                if len(p) >= 6:
                    # idA idB sA eA sB eB  (token indices, same order as the ids)
                    r.update(sA=int(p[2]), eA=int(p[3]), sB=int(p[4]), eB=int(p[5]))
                rows.append(r)
    topn = len(rows)
else:
    rows = list(csv.DictReader(open(os.path.join(outd, 'top_pairs.csv'), encoding='utf-8')))
art = lambda x: x.split(' | ')[0] if ' | ' in x else x


def seg(i, s, e):
    p = parse_abc(songs[meta[i]['id']]['abc']); notes = p.voices[meta[i]['voice']][s:e + 3]
    t0 = notes[0].onset
    return [(n.onset - t0, n.dur, n.midi) for n in notes]


os.makedirs(os.path.join(outd, 'listen'), exist_ok=True)
k = 0
for r in rows:
    if not explicit:
        if r['known_relation'] or float(r['raw_score']) >= 50 or float(r['trivial_fraction']) > .5 or int(r['distinct_tokens']) < 8: continue
    if r['id_A'] not in byid or r['id_B'] not in byid:
        print('skip (unknown id):', r['id_A'], r['id_B']); continue
    a, b = byid[r['id_A']], byid[r['id_B']]
    if 'sA' in r:
        sA, eA, sB, eB = r['sA'], r['eA'], r['sB'], r['eB']
    else:
        kk = pid[(min(a, b), max(a, b))]; sA, eA, sB, eB = [int(v) for v in res[kk, 1:5]]
    if a > b: a, b, sA, eA, sB, eB = b, a, sB, eB, sA, eA
    A = seg(a, sA, eA); B = seg(b, sB, eB)
    la = A[-1][0] + A[-1][1]; lb = B[-1][0] + B[-1][1]; sc = la / lb
    B = [(o * sc, d * sc, m + (A[0][2] - B[0][2])) for o, d, m in B]
    mid = mido.MidiFile(ticks_per_beat=480); tr = mido.MidiTrack(); mid.tracks.append(tr)
    tr.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(100)))
    ev = [(o, d, m) for o, d, m in A] + [(la + 2 + o, d, m) for o, d, m in B]
    msgs = []
    for o, d, m in ev:
        msgs.append((o, 1, m)); msgs.append((o + max(d * .95, .1), 0, m))
    msgs.sort(key=lambda x: (x[0], x[1])); last = 0
    for t, on, m in msgs:
        tr.append(mido.Message('note_on' if on else 'note_off', note=int(min(max(m, 0), 127)), velocity=80 if on else 0, time=int(round((t - last) * 480)))); last = t
    prefix = (tag + '_') if tag else ''
    name = '%02d_%s%s__%s.mid' % (k + 1, prefix, ''.join(c for c in meta[a]['title'] if c.isalnum())[:20], ''.join(c for c in meta[b]['title'] if c.isalnum())[:20])
    mid.save(os.path.join(outd, 'listen', name)); print(name, r.get('raw_score', ''), r.get('matched_beats', ''), 'beats'); k += 1
    if k >= topn: break
