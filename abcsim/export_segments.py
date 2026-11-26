"""export_segments.py -- write the matched passages of the top candidate pairs as MIDI so you can LISTEN to them.
Each file = passage from song A, 2 s pause, passage from song B (B moved to A's key, stretched to A's length)."""
import sys, os, csv, pickle
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, mido
from corpus import load_all
from parse import parse_abc

root = sys.argv[1]; outd = sys.argv[2]; os.makedirs(outd, exist_ok=True); topn = int(sys.argv[3]) if len(sys.argv) > 3 else 8
idx = pickle.load(open(os.path.join(outd, 'index.pkl'), 'rb')); meta = idx['meta']
d = np.load(os.path.join(outd, 'pairs_raw.npz')); pairs = d['pairs']; res = d['res']
pid = {(int(a), int(b)): k for k, (a, b) in enumerate(pairs)}
byid = {m['id']: i for i, m in enumerate(meta)}
songs = {s['id']: s for s in load_all(root)}
rows = list(csv.DictReader(open(os.path.join(outd, 'top_pairs.csv'), encoding='utf-8')))
art = lambda x: x.split(' | ')[0] if ' | ' in x else x


def seg(i, s, e):
    p = parse_abc(songs[meta[i]['id']]['abc']); notes = p.voices[meta[i]['voice']][s:e + 3]
    t0 = notes[0].onset
    return [(n.onset - t0, n.dur, n.midi) for n in notes]


os.makedirs(os.path.join(outd, 'listen'), exist_ok=True)
k = 0
for r in rows:
    if r['known_relation'] or float(r['raw_score']) >= 50 or float(r['trivial_fraction']) > .5 or int(r['distinct_tokens']) < 8: continue
    a, b = byid[r['id_A']], byid[r['id_B']]
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
    name = '%02d_%s__%s.mid' % (k + 1, ''.join(c for c in meta[a]['title'] if c.isalnum())[:20], ''.join(c for c in meta[b]['title'] if c.isalnum())[:20])
    mid.save(os.path.join(outd, 'listen', name)); print(name, r['raw_score'], r['matched_beats'], 'beats'); k += 1
    if k >= topn: break
