"""run_chordmap.py -- what chord progressions are 'normal' in the library? Output: out/chord_progressions.csv, out/chordmap.png"""
import sys, os, re, csv, collections
sys.path.insert(0, os.path.dirname(__file__))
from corpus import load_all
from parse import parse_abc, PC

ROMAN = ['I', 'bII', 'II', 'bIII', 'III', 'IV', '#IV', 'V', 'bVI', 'VI', 'bVII', 'VII']
CH = re.compile(r'^([A-G][b#]?)(.*)$')


def chord_label(sym, tonic):
    m = CH.match(sym)
    if not m or m.group(1) not in PC:
        return None
    q = m.group(2).split('/')[0]
    deg = (PC[m.group(1)] - tonic) % 12
    if q.startswith('m7b5') or q.startswith('dim'):
        return ROMAN[deg].lower() + 'o'
    minor = q.startswith('m') and not q.startswith('maj')
    lab = ROMAN[deg].lower() if minor else ROMAN[deg]
    if (not minor) and re.match(r'^7|^9|^11|^13', q):
        lab += '7'
    return lab


def progression(p):
    seq = []
    for t, sym, bar, v in sorted(p.chords, key=lambda x: x[0]):
        lab = chord_label(sym, p.tonic)
        if lab and (not seq or seq[-1] != lab):
            seq.append(lab)
    return seq


if __name__ == '__main__':
    root = sys.argv[1]; outd = sys.argv[2] if len(sys.argv) > 2 else 'out'; os.makedirs(outd, exist_ok=True)
    N = 4
    df = collections.Counter(); df1 = collections.Counter(); nsong = 0; per_song = {}
    allsongs = load_all(root)
    use = [s for s in allsongs if s['corpus'] in ('FADL', 'YT500')] or allsongs
    for s in use:
        p = parse_abc(s['abc']); seq = progression(p)
        if len(seq) < N: continue
        nsong += 1
        grams = {tuple(seq[i:i + N]) for i in range(len(seq) - N + 1)}
        df.update(grams); df1.update(set(seq))
        per_song[s['id']] = (grams, len(seq))
    rows = [dict(progression=' - '.join(g), songs=c, pct=round(100 * c / nsong, 1)) for g, c in df.most_common(40)]
    with open(os.path.join(outd, 'chord_progressions.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['progression', 'songs', 'pct']); w.writeheader(); w.writerows(rows)
    print('songs:', nsong, '| distinct 4-chord progressions:', len(df))
    for r in rows[:12]: print(' %5.1f%%  %s' % (r['pct'], r['progression']))
    top = df.most_common(1)[0]
    cover = sum(1 for g, _ in per_song.values() if any(df[x] >= 0.05 * nsong for x in g))
    print('songs containing at least one progression found in >=5%% of songs: %d/%d' % (cover, nsong))
    import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
    top = rows[:15][::-1]
    plt.figure(figsize=(8, 5.5)); plt.barh([r['progression'] for r in top], [r['pct'] for r in top], color='#3b6ea5')
    plt.xlabel('% of songs containing it'); plt.title('Most common 4-chord progressions (relative to key), %d songs' % nsong)
    plt.tight_layout(); plt.savefig(os.path.join(outd, 'chordmap.png'), dpi=130)
