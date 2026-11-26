"""run_validate.py -- sanity-check every score. Output: out/validation.csv"""
import sys, csv, os, collections
sys.path.insert(0, os.path.dirname(__file__))
from corpus import load_all
from parse import parse_abc, lead_voice

root = sys.argv[1]; outd = sys.argv[2] if len(sys.argv) > 2 else 'out'
os.makedirs(outd, exist_ok=True)
rows = []
for s in load_all(root):
    p = parse_abc(s['abc'])
    lv = lead_voice(p)
    n = {k: len(v) for k, v in p.voices.items()}
    dur_q = max(p.total_q.values()) if p.total_q else 0
    sec = dur_q * 60.0 / p.tempo
    lead = p.voices.get(lv, []) if lv else []
    pitches = [x.midi for x in lead]
    rep = (sum(1 for a, b in zip(pitches, pitches[1:]) if a == b) / max(1, len(pitches) - 1)) if lead else 0
    flags = []
    if lv is None: flags.append('no-melody')
    if sum(p.bad_bars.values()): flags.append('bad-bars:%d' % sum(p.bad_bars.values()))
    if p.issues: flags.append('unparsed:%d' % len(p.issues))
    if lead and sec > 0 and len(lead) / sec < 0.3: flags.append('sparse')
    if lead and sec > 0 and len(lead) / sec > 8: flags.append('too-dense')
    if lead and rep > 0.6: flags.append('repeat-heavy')
    if not p.chords: flags.append('no-chords')
    if p.tempo < 50 or p.tempo > 200: flags.append('odd-tempo')
    if lead and (max(pitches) - min(pitches)) > 40: flags.append('huge-range')
    rows.append(dict(id=s['id'], corpus=s['corpus'], artist=s['artist'], title=s['title'], key=p.key, tempo=p.tempo,
                     seconds=round(sec, 1), lead=lv, n_vocal=n.get('Vocal', 0), n_ins=n.get('Ins', 0),
                     bars=max(p.n_bars.values()) if p.n_bars else 0, chords=len(p.chords),
                     pitch_range=(max(pitches) - min(pitches)) if lead else 0, repeated_note_ratio=round(rep, 2),
                     flags=';'.join(flags)))
with open(os.path.join(outd, 'validation.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
c = collections.Counter(fl.split(':')[0] for r in rows for fl in r['flags'].split(';') if fl)
print('scores:', len(rows), '| flagged:', sum(1 for r in rows if r['flags']), '| flag types:', dict(c))
