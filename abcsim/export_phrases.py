"""export_phrases.py -- build a small, diverse bank of real vocal phrases.

The bank is written in the abc-score-writer Blueprint note grammar:

    degree:beats          e.g. b3:0.5 4:1 5:2~
    r:<beats>             timed rest

Degrees are key-relative.  The script uses the same convention as Repo B's
abc_common.degree_to_midi: degree 1 is the tonic in octave 4, trailing +/-
shift octaves, and semitone 6 is spelled b5.

Input : out/dedupe_keep.txt, out/clusters.json, out/validation.csv, the corpus
Output: handoff/skill_0.2.3/assets/phrase_bank.json

The corpus has no lyrics, so roles are inferred only from cadence and phrase
length.  The JSON field is deliberately named role_hint, never role.
"""
import argparse
import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from corpus import load_all
from parse import parse_abc

DEGREE_BY_PC = {0: '1', 1: 'b2', 2: '2', 3: 'b3', 4: '3', 5: '4',
                6: 'b5', 7: '5', 8: 'b6', 9: '6', 10: 'b7', 11: '7'}
PC_BY_DEGREE = {v: k for k, v in DEGREE_BY_PC.items()}
NATURAL = {1: 0, 2: 2, 3: 4, 4: 5, 5: 7, 6: 9, 7: 11}

MAQAM_TEMPLATES = {
    'kurd-like': [0, 1, 3, 8, 10],
    'hijaz-like': [0, 1, 4, 8, 10],
    'nahawand-like': [0, 2, 3, 5, 7, 8, 10],
    'rast-like': [0, 2, 4, 5, 7, 9, 10],
    'bayati-like': [0, 1, 4, 5, 7, 9, 10],
    'saba-like': [0, 1, 4, 5, 6, 8, 10],
    'major-like': [0, 2, 4, 5, 7, 9, 11],
}

TARGET_BEATS = (16, 8)
TARGET_PER_CLASS = 24
MIN_PER_CLASS = 20


# --------------------------------------------------------------------------- degree helpers
def degree_to_midi_local(degree, tonic_midi):
    """Same arithmetic as Repo B's abc_common.degree_to_midi (no key spelling)."""
    s = degree.strip()
    acc = 0
    while s and s[0] in '#b':
        acc += 1 if s[0] == '#' else -1
        s = s[1:]
    if not s or s[0] not in '1234567':
        raise ValueError('bad degree: %r' % degree)
    num = int(s[0])
    rest = s[1:]
    oct_shift = rest.count('+') - rest.count('-')
    return tonic_midi + NATURAL[num] + acc + 12 * oct_shift


def degree_for_midi(midi, tonic_midi):
    """MIDI -> (degree string, pitch-class offset 0..11)."""
    rel = int(round(midi)) - tonic_midi
    octave = rel // 12
    pc = rel - 12 * octave
    deg = DEGREE_BY_PC[pc]
    if octave > 0:
        deg += '+' * octave
    elif octave < 0:
        deg += '-' * (-octave)
    return deg, pc


def fmt_beats(x):
    x = round(float(x), 4)
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    s = ('%.4f' % x).rstrip('0').rstrip('.')
    return s


def note_tokens(deg, beats):
    """Split >4-beat notes into tied chunks the grammar accepts."""
    out = []
    left = float(beats)
    while left > 4.0 + 1e-9:
        out.append('%s:4~' % deg)
        left -= 4.0
    out.append('%s:%s' % (deg, fmt_beats(left)))
    return out


def rest_tokens(beats):
    out = []
    left = float(beats)
    while left > 4.0 + 1e-9:
        out.append('r:4')
        left -= 4.0
    if left > 1e-9:
        out.append('r:%s' % fmt_beats(left))
    return out


def end_degree_class(midi, tonic_midi):
    return DEGREE_BY_PC[(int(round(midi)) - tonic_midi) % 12]


def cadence_for(end_deg, beats):
    """Heuristic sadr/ajuz classification, matching the skill's cadence rules."""
    if end_deg in ('2', '4'):
        return 'sadr', 'sadr'
    if end_deg == '5':
        if beats >= 16:
            return 'sadr', 'sadr_or_ajuz'
        return 'ajuz', 'sadr_or_ajuz'
    if end_deg == '1':
        return 'ajuz', 'ajuz (assumes section end)'
    return 'other', 'unknown'


def mode_hint(pc_counts, total, minor):
    if total <= 0:
        return 'unknown'
    best_name, best_score = ('minor-like' if minor else 'major-like'), 0.0
    for name, pcs in MAQAM_TEMPLATES.items():
        score = sum(pc_counts.get(pc, 0) for pc in pcs) / float(total)
        if score > best_score + 1e-9:
            best_name, best_score = name, score
    # A very weak match is safer as a plain minor/major label.
    if best_score < 0.45:
        return 'minor-like' if minor else 'major-like'
    return best_name


def register_for(midi):
    if midi < 64:
        return 'low'
    if midi < 72:
        return 'mid'
    return 'high'


# --------------------------------------------------------------------------- candidates
def starts_of(notes):
    """Bar starts plus note starts that follow a real (>=1 beat) rest."""
    out = set()
    for i, n in enumerate(notes):
        if i == 0:
            out.add(i)
            continue
        prev = notes[i - 1]
        gap = n.onset - (prev.onset + prev.dur)
        if n.bar != prev.bar or gap >= 1.0 - 1e-6:
            out.add(i)
    return sorted(out)


def phrase_from(notes, i, target, tonic_midi):
    start = notes[i].onset
    end_limit = start + target
    seq = []
    for n in notes[i:]:
        if n.onset >= end_limit - 1e-6:
            break
        if n.onset + n.dur > end_limit + 1e-6:
            break
        seq.append(n)
    if len(seq) < 5:
        return None
    span = seq[-1].onset + seq[-1].dur - start
    if span < target - 1.0 - 1e-6:
        return None

    # grid + no long internal rest/overlap
    for k, n in enumerate(seq):
        if abs(n.dur * 4 - round(n.dur * 4)) > 1e-6:
            return None
        if k:
            gap = n.onset - (seq[k - 1].onset + seq[k - 1].dur)
            if gap < -0.05 or gap >= 1.0 - 1e-6:
                return None
            if gap >= 0.25 - 1e-6 and abs(gap * 4 - round(gap * 4)) > 1e-6:
                return None

    pitches = [n.midi for n in seq]
    if len(set(pitches)) < 5:
        return None
    if max(pitches) - min(pitches) > 12:
        return None
    rep = sum(1 for a, b in zip(pitches, pitches[1:]) if a == b) / max(1, len(pitches) - 1)
    if rep >= 0.5:
        return None

    tokens = []
    source_midi = []
    pc_counts = Counter()
    for k, n in enumerate(seq):
        if k:
            gap = n.onset - (seq[k - 1].onset + seq[k - 1].dur)
            if gap >= 0.25 - 1e-6:
                tokens.extend(rest_tokens(round(gap * 4) / 4.0))
        deg, pc = degree_for_midi(n.midi, tonic_midi)
        if degree_to_midi_local(deg, tonic_midi) != int(round(n.midi)):
            return None
        tokens.extend(note_tokens(deg, n.dur))
        source_midi.append(int(round(n.midi)))
        pc_counts[pc] += 1

    used = span
    if target - used >= 0.25 - 1e-6:
        tokens.extend(rest_tokens(round((target - used) * 4) / 4.0))
        used += round((target - used) * 4) / 4.0
    if abs(used - target) > 0.01:
        return None

    end_deg = end_degree_class(seq[-1].midi, tonic_midi)
    cadence, role = cadence_for(end_deg, target)
    if cadence == 'other':
        return None
    return dict(
        beats=target,
        phrase=' '.join(tokens),
        end_degree=end_deg,
        cadence_class=cadence,
        role_hint=role,
        mode_hint=mode_hint(pc_counts, sum(pc_counts.values()), False),
        source_midi=source_midi,
        source_bars=[int(seq[0].bar) + 1, int(seq[-1].bar) + 1],
        register=register_for(sorted(pitches)[len(pitches) // 2]),
        distinct_pitches=len(set(pitches)),
        repeated_note_ratio=round(rep, 3),
        span=int(max(pitches) - min(pitches)),
        _seq=[(int(n.midi), float(n.dur), float(n.onset)) for n in seq],
    )


# --------------------------------------------------------------------------- diversity
def phrase_vector(p):
    iv = [0.0] * 25
    for a, b in zip(p['source_midi'], p['source_midi'][1:]):
        d = max(-12, min(12, b - a))
        iv[d + 12] += 1.0
    dur = [0.0] * 8
    bins = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]
    for _, d, _ in p['_seq']:
        j = min(range(len(bins)), key=lambda k: abs(bins[k] - d))
        dur[j] += 1.0
    n = max(1.0, sum(iv)); m = max(1.0, sum(dur))
    return [x / n for x in iv] + [x / m for x in dur]


def dist(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def select_diverse(cands, k):
    """Greedy farthest-point pick with the cluster/source caps."""
    if not cands:
        return []
    for c in cands:
        c['_vec'] = phrase_vector(c)
    # start near the centroid so the bank is not anchored on an outlier
    dim = len(cands[0]['_vec'])
    cen = [sum(c['_vec'][i] for c in cands) / len(cands) for i in range(dim)]
    first = min(cands, key=lambda c: dist(c['_vec'], cen))
    chosen = [first]
    chosen_ids = {id(first)}
    used_cluster = {first['cluster']}
    used_source = Counter({first['source_id']: 1})
    while len(chosen) < k:
        best = None
        for c in cands:
            if id(c) in chosen_ids or c['cluster'] in used_cluster:
                continue
            if used_source[c['source_id']] >= 3:
                continue
            d = min(dist(c['_vec'], s['_vec']) for s in chosen)
            if best is None or d > best[0]:
                best = (d, c)
        if best is None:
            break
        c = best[1]
        chosen.append(c)
        chosen_ids.add(id(c))
        used_cluster.add(c['cluster'])
        used_source[c['source_id']] += 1
    return chosen


# --------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('corpus', help='folder containing the .abc files')
    ap.add_argument('outd', nargs='?', default='out')
    ap.add_argument('--out', default='handoff/skill_0.2.3/assets/phrase_bank.json')
    ap.add_argument('--per-class', type=int, default=TARGET_PER_CLASS)
    args = ap.parse_args(argv)

    outd = Path(args.outd)
    keep = [x.strip() for x in (outd / 'dedupe_keep.txt').read_text(encoding='utf-8').splitlines() if x.strip()]
    keep_set = set(keep)
    clusters = json.loads((outd / 'clusters.json').read_text(encoding='utf-8'))
    cluster_of = {}
    for c in clusters['clusters']:
        for m in c['members']:
            cluster_of[m['id']] = c['id']
    for sid in clusters['singletons']:
        cluster_of[sid] = 'S:' + sid

    flags = {}
    with open(outd / 'validation.csv', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            flags[r['id']] = r.get('flags', '')

    candidates = []
    skipped_songs = 0
    for s in load_all(args.corpus):
        if s['id'] not in keep_set:
            continue
        if 'bad-bars' in flags.get(s['id'], ''):
            skipped_songs += 1
            continue
        song = parse_abc(s['abc'])
        notes = song.voices.get('Vocal', [])
        if len(notes) < 8:
            skipped_songs += 1
            continue
        tonic_midi = 60 + int(song.tonic)
        seen = set()
        for target in TARGET_BEATS:
            for i in starts_of(notes):
                p = phrase_from(notes, i, target, tonic_midi)
                if p is None:
                    continue
                key = (target, p['source_bars'][0], p['source_bars'][1], tuple(p['source_midi']))
                if key in seen:
                    continue
                seen.add(key)
                p['source_id'] = s['id']
                p['source_key'] = song.key
                p['cluster'] = cluster_of.get(s['id'], 'S:' + s['id'])
                p['mode_hint'] = mode_hint(
                    Counter((m - tonic_midi) % 12 for m in p['source_midi']),
                    len(p['source_midi']), bool(song.minor))
                candidates.append(p)

    # at most one phrase per cluster per class is enforced during selection
    by_class = defaultdict(list)
    for p in candidates:
        by_class[p['cadence_class']].append(p)
    chosen = []
    for cls in ('sadr', 'ajuz'):
        chosen.extend(select_diverse(by_class.get(cls, []), args.per_class))

    chosen.sort(key=lambda p: (p['cadence_class'], p['source_id'], p['source_bars']))
    for i, p in enumerate(chosen, 1):
        p['id'] = 'P%03d' % i
        p.pop('_vec', None)
        p.pop('_seq', None)

    counts_cls = Counter(p['cadence_class'] for p in chosen)
    counts_reg = Counter(p['register'] for p in chosen)
    counts_mode = Counter(p['mode_hint'] for p in chosen)
    counts_beats = Counter(p['beats'] for p in chosen)
    payload = dict(
        schema=1,
        generated_from=dict(corpus='deduped 599-file set', roles='heuristic from cadence + length',
                            degree_convention='Repo B abc_common.degree_to_midi; semitone 6 = b5'),
        grammar=dict(note='degree:beats', rest='r:<beats>', tie='trailing ~',
                     degrees=list(DEGREE_BY_PC.values())),
        counts=dict(by_cadence_class=dict(counts_cls), by_register=dict(counts_reg),
                    by_mode_hint=dict(counts_mode), by_beats=dict(counts_beats),
                    candidates=len(candidates), skipped_songs=skipped_songs),
        phrases=chosen,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=1) + '\n'
    if len(text.encode('utf-8')) > 60 * 1024:
        text = json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n'
    out.write_text(text, encoding='utf-8', newline='\n')

    print('candidates:', len(candidates), '| skipped songs:', skipped_songs)
    print('chosen:', len(chosen), '| by class:', dict(counts_cls))
    print('by register:', dict(counts_reg))
    print('by mode_hint:', dict(counts_mode))
    print('by beats:', dict(counts_beats))
    print('wrote %s (%.1f KB)' % (out, len(text.encode('utf-8')) / 1024.0))
    if any(counts_cls.get(c, 0) < MIN_PER_CLASS for c in ('sadr', 'ajuz')):
        print('WARNING: fewer than %d phrases in a cadence class' % MIN_PER_CLASS)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
