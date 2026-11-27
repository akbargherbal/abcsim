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

Schema phrase_bank/2 adds phrase_bytes, fits_seed_budget, a per-mode quota
(--min-per-mode, --modes) with explicit counts.mode_shortfall, and a candidate
byte filter (--max-phrase-bytes).  Degrees are tonic-relative: source_key is
provenance only and must not be shown as a transposition.

Reproduce the shipped bank:
    python abcsim/export_phrases.py CORPUS_ROOT out
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

LEGACY_MAQAM_TEMPLATES = {
    'kurd-like': [0, 1, 3, 8, 10],
    'hijaz-like': [0, 1, 4, 8, 10],
    'nahawand-like': [0, 2, 3, 5, 7, 8, 10],
    'rast-like': [0, 2, 4, 5, 7, 9, 10],
    'bayati-like': [0, 1, 4, 5, 7, 9, 10],
    'saba-like': [0, 1, 4, 5, 6, 8, 10],
    'major-like': [0, 2, 4, 5, 7, 9, 11],
}

# Scale templates as pitch classes relative to the tonic.  Source: Repo B
# references/maqam.md (the skill's own 12-tone definitions); where this file
# differs from the follow-up plan, maqam.md wins and the difference is noted.
#   core      : the scale tones
#   tolerated : tones that do not count against the template (but are not
#               needed either)
#   requires_all / requires_any : evidence the phrase must contain before the
#               template may be named at all (distinguishing degrees)
#   branch    : 'b2' templates need the flat second, 'n2' templates the
#               natural second.
# Approximations (12-TET, no quarter tones):
#   kurd     1 b2 b3 4 5 b6 b7   = maqam.md.
#   hijaz    1 b2 3 4 5 b6 b7    = maqam.md; needs the natural 3 (aug. 2nd).
#   bayati   maqam.md lists exactly the Kurd scale ("close to Kurd here"), so
#            the two are not separable in 12-TET.  bayati-like is therefore
#            defined by the one sign that does separate them in this corpus
#            context: b2 + b3 + a NATURAL 6 (the plan's {0,1,3,5,7,9,10}).
#   saba     maqam.md 1 b2 b3 b5 5 b6 b7; needs the b5.  Natural 3 (the
#            enharmonic flat 4th) is tolerated.
#   nahawand natural minor; the raised 7 (harmonic minor) is tolerated.
#   rast     1 2 3 4 5 6 b7 (maqam.md); needs the b7 so it is not just major.
#   major    1 2 3 4 5 6 7.
MAQAM_TEMPLATES = {
    'kurd-like': dict(core=[0, 1, 3, 5, 7, 8, 10], tolerated=[], branch='b2',
                      requires_all=[], requires_any=[3, 8]),
    'hijaz-like': dict(core=[0, 1, 4, 5, 7, 8, 10], tolerated=[], branch='b2',
                       requires_all=[4], requires_any=[]),
    'bayati-like': dict(core=[0, 1, 3, 5, 7, 9, 10], tolerated=[], branch='b2',
                        requires_all=[3, 9], requires_any=[]),
    'saba-like': dict(core=[0, 1, 3, 6, 7, 8, 10], tolerated=[4], branch='b2',
                      requires_all=[3, 6], requires_any=[]),
    'nahawand-like': dict(core=[0, 2, 3, 5, 7, 8, 10], tolerated=[11], branch='n2',
                          requires_all=[], requires_any=[3, 8]),
    'rast-like': dict(core=[0, 2, 4, 5, 7, 9, 10], tolerated=[], branch='n2',
                      requires_all=[10], requires_any=[4, 9]),
    'major-like': dict(core=[0, 2, 4, 5, 7, 9, 11], tolerated=[], branch='n2',
                       requires_all=[], requires_any=[4, 11]),
}
MIN_MODE_NOTES = 6        # fewer notes than this is too little evidence
MIN_MODE_SHARE = 0.70     # share of notes that must sit inside the template

TARGET_BEATS = (16, 8)
TARGET_PER_CLASS = 24
MIN_PER_CLASS = 20
MAX_PER_CLASS = 28
SCHEMA = 'phrase_bank/2'
SEED_BUDGET_BYTES = 130          # fits_seed_budget threshold (phrase text only)
DEFAULT_MAX_PHRASE_BYTES = 130   # export default; 0 disables the filter
DEFAULT_MIN_PER_MODE = 4
DEFAULT_MODES = ('kurd-like', 'hijaz-like', 'bayati-like', 'rast-like', 'nahawand-like')


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


def mode_hint_legacy(pc_counts, total, minor):
    """0.2.3 classifier (share of notes inside a template). Kept only so
    audit_modes can print an old-versus-new confusion matrix."""
    if total <= 0:
        return 'unknown'
    best_name, best_score = ('minor-like' if minor else 'major-like'), 0.0
    for name, pcs in LEGACY_MAQAM_TEMPLATES.items():
        score = sum(pc_counts.get(pc, 0) for pc in pcs) / float(total)
        if score > best_score + 1e-9:
            best_name, best_score = name, score
    # A very weak match is safer as a plain minor/major label.
    if best_score < 0.45:
        return 'minor-like' if minor else 'major-like'
    return best_name


def mode_hint(pc_counts, total, minor):
    """Two-stage maqam hint.

    Stage 1 (distinguishing degrees): decide between the b2 family (kurd,
    hijaz, bayati, saba) and the natural-2 family (nahawand, rast, major) from
    which second occurs more often.  A phrase with neither, or with the two in
    near balance, is ambiguous and gets the plain minor-like / major-like label.
    Stage 2: among templates whose required degrees are present, pick the best
    share of notes inside the template, then the fewest unused template tones,
    then template order.  A weak best share also falls back to the plain label.
    """
    generic = 'minor-like' if minor else 'major-like'
    if total < MIN_MODE_NOTES:
        return generic
    n_b2 = pc_counts.get(1, 0)
    n_2 = pc_counts.get(2, 0)
    if n_b2 == 0 and n_2 == 0:
        return generic
    if n_b2 >= 2 * n_2:
        branch = 'b2'
    elif n_2 >= 2 * n_b2:
        branch = 'n2'
    else:
        return generic          # b2 and 2 in near balance: no clear family
    present = {pc for pc, c in pc_counts.items() if c > 0}
    best, best_key = None, None
    for order, (name, t) in enumerate(MAQAM_TEMPLATES.items()):
        if t['branch'] != branch:
            continue
        if not all(pc in present for pc in t['requires_all']):
            continue
        if t['requires_any'] and not any(pc in present for pc in t['requires_any']):
            continue
        allowed = set(t['core']) | set(t['tolerated'])
        share = sum(c for pc, c in pc_counts.items() if pc in allowed) / float(total)
        unused = len(set(t['core']) - present)
        key = (-round(share, 6), unused, order)
        if best_key is None or key < best_key:
            best, best_key = name, key
    if best is None or -best_key[0] < MIN_MODE_SHARE:
        return generic
    return best


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


def _pick(pool, count, chosen, state):
    """Farthest-point picks from `pool`, appended to `chosen`; returns how many.

    state = dict(ids=set of id(), clusters=set, sources=Counter) shared across
    calls so the one-per-cluster and at-most-3-per-source caps hold globally.
    With nothing chosen yet the first pick is the candidate nearest the pool
    centroid, so the bank is not anchored on an outlier.
    """
    added = 0
    while added < count:
        eligible = [c for c in pool
                    if id(c) not in state['ids'] and c['cluster'] not in state['clusters']
                    and state['sources'][c['source_id']] < 3]
        if not eligible:
            break
        if not chosen:
            dim = len(eligible[0]['_vec'])
            cen = [sum(c['_vec'][i] for c in eligible) / len(eligible) for i in range(dim)]
            best = min(eligible, key=lambda c: dist(c['_vec'], cen))
        else:
            best, best_d = None, -1.0
            for c in eligible:
                d = min(dist(c['_vec'], s['_vec']) for s in chosen)
                if d > best_d:
                    best, best_d = c, d
        chosen.append(best)
        state['ids'].add(id(best))
        state['clusters'].add(best['cluster'])
        state['sources'][best['source_id']] += 1
        added += 1
    return added


def select_diverse(cands, k, modes=(), min_per_mode=0):
    """Pick up to k phrases from one cadence class.

    1. For each requested mode (rarest candidate pool first, so it gets first
       call on the cluster/source caps) pick up to `min_per_mode` phrases by
       farthest-point WITHIN that mode's candidates.
    2. Fill the remaining slots by farthest-point over all candidates.

    Returns (chosen, shortfall) where shortfall maps mode -> (wanted, got) for
    every mode that could not reach `min_per_mode`.  Nothing is padded with
    mislabeled phrases.  With no modes this is the original 0.2.3 selection.
    """
    if not cands:
        return [], {m: (min_per_mode, 0) for m in modes} if min_per_mode else {}
    for c in cands:
        c['_vec'] = phrase_vector(c)
    chosen = []
    state = dict(ids=set(), clusters=set(), sources=Counter())
    shortfall = {}
    if min_per_mode > 0:
        pools = {m: [c for c in cands if c['mode_hint'] == m] for m in modes}
        for m in sorted(modes, key=lambda m: (len(pools[m]), m)):
            got = _pick(pools[m], min_per_mode, chosen, state)
            if got < min_per_mode:
                shortfall[m] = (min_per_mode, got)
    _pick(cands, k - len(chosen), chosen, state)
    return chosen, shortfall


# --------------------------------------------------------------------------- candidate generation
def generate_candidates(corpus, outd):
    """Build every phrase candidate from the deduped kept songs.

    Shared by export_phrases.main and audit_modes so both see identical data.
    Returns (candidates, skipped_songs, songs) where songs is one dict per
    usable song: id, key, minor, tonic_midi and pc_counts over the WHOLE vocal
    stream (pitch classes relative to the tonic).
    """
    outd = Path(outd)
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
    songs = []
    skipped_songs = 0
    for s in load_all(corpus):
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
        songs.append(dict(id=s['id'], key=song.key, minor=bool(song.minor), tonic_midi=tonic_midi,
                          pc_counts=Counter((int(round(n.midi)) - tonic_midi) % 12 for n in notes)))
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
                p['_pcs'] = dict(Counter((m - tonic_midi) % 12 for m in p['source_midi']))
                p['mode_hint'] = mode_hint(p['_pcs'], len(p['source_midi']), bool(song.minor))
                candidates.append(p)
    return candidates, skipped_songs, songs


# --------------------------------------------------------------------------- main
def seed_budget_stats(cands, limit):
    """Fitting / non-fitting counts per cadence class, per mode and per length."""
    out = dict(limit_bytes=limit, fit=0, over=0, by_cadence_class={}, by_mode={}, by_beats={})
    for c in cands:
        fit = c['phrase_bytes'] <= limit
        out['fit' if fit else 'over'] += 1
        for key, val in (('by_cadence_class', c['cadence_class']), ('by_mode', c['mode_hint']),
                         ('by_beats', str(c['beats']))):
            d = out[key].setdefault(val, dict(fit=0, over=0))
            d['fit' if fit else 'over'] += 1
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('corpus', help='folder containing the .abc files')
    ap.add_argument('outd', nargs='?', default='out')
    ap.add_argument('--out', default='handoff/skill_0.2.3/assets/phrase_bank.json')
    ap.add_argument('--per-class', type=int, default=TARGET_PER_CLASS)
    ap.add_argument('--min-per-mode', type=int, default=DEFAULT_MIN_PER_MODE,
                    help='quota of phrases per requested mode and cadence class (default %(default)s; 0 disables)')
    ap.add_argument('--modes', default=','.join(DEFAULT_MODES),
                    help='comma-separated modes that get the quota (default: %(default)s)')
    ap.add_argument('--max-phrase-bytes', type=int, default=DEFAULT_MAX_PHRASE_BYTES,
                    help='exclude candidates whose phrase text is longer than this many UTF-8 '
                         'bytes before selection (default %(default)s; 0 = no limit)')
    args = ap.parse_args(argv)

    modes = [m.strip() for m in args.modes.split(',') if m.strip()]
    unknown = [m for m in modes if m not in MAQAM_TEMPLATES and m not in ('minor-like', 'major-like')]
    if unknown:
        ap.error('unknown mode(s): %s' % ', '.join(unknown))
    per_class = max(args.per_class, args.min_per_mode * len(modes))
    if per_class > MAX_PER_CLASS:
        ap.error('quota %d x %d modes needs %d phrases per class; the limit is %d'
                 % (args.min_per_mode, len(modes), per_class, MAX_PER_CLASS))

    candidates, skipped_songs, _songs = generate_candidates(args.corpus, args.outd)
    for p in candidates:
        p['phrase_bytes'] = len(p['phrase'].encode('utf-8'))
        p['fits_seed_budget'] = p['phrase_bytes'] <= SEED_BUDGET_BYTES
    budget_all = seed_budget_stats(candidates, SEED_BUDGET_BYTES)
    n_all = len(candidates)
    if args.max_phrase_bytes > 0:
        candidates = [p for p in candidates if p['phrase_bytes'] <= args.max_phrase_bytes]

    # at most one phrase per cluster per class is enforced during selection
    by_class = defaultdict(list)
    for p in candidates:
        by_class[p['cadence_class']].append(p)
    chosen = []
    shortfall = {}        # mode -> dict(wanted, got, by_cadence_class)
    for cls in ('sadr', 'ajuz'):
        picked, short = select_diverse(by_class.get(cls, []), per_class, modes, args.min_per_mode)
        chosen.extend(picked)
        for m, (want, got) in short.items():
            e = shortfall.setdefault(m, dict(wanted=0, got=0, by_cadence_class={}))
            e['wanted'] += want
            e['got'] += got
            e['by_cadence_class'][cls] = dict(wanted=want, got=got)

    chosen.sort(key=lambda p: (p['cadence_class'], p['source_id'], p['source_bars']))
    for i, p in enumerate(chosen, 1):
        p['id'] = 'P%03d' % i
        p.pop('_vec', None)
        p.pop('_seq', None)
        p.pop('_pcs', None)

    counts_cls = Counter(p['cadence_class'] for p in chosen)
    counts_reg = Counter(p['register'] for p in chosen)
    counts_mode = Counter(p['mode_hint'] for p in chosen)
    counts_beats = Counter(p['beats'] for p in chosen)
    budget_bank = seed_budget_stats(chosen, SEED_BUDGET_BYTES)
    payload = dict(
        schema=SCHEMA,
        generated_from=dict(corpus='deduped 599-file set', roles='heuristic from cadence + length',
                            degree_convention='Repo B abc_common.degree_to_midi; semitone 6 = b5',
                            mode_hint='two-stage classifier, export_phrases.mode_hint; degrees are '
                                      'tonic-relative, not tied to source_key',
                            selection=dict(min_per_mode=args.min_per_mode, modes=modes,
                                           max_phrase_bytes=args.max_phrase_bytes, per_class=per_class)),
        grammar=dict(note='degree:beats', rest='r:<beats>', tie='trailing ~',
                     degrees=list(DEGREE_BY_PC.values()),
                     fields_added_in_schema_2=['phrase_bytes', 'fits_seed_budget',
                                               'counts.mode_shortfall', 'counts.seed_budget',
                                               'counts.min_per_mode']),
        counts=dict(by_cadence_class=dict(counts_cls), by_register=dict(counts_reg),
                    by_mode_hint=dict(counts_mode), by_beats=dict(counts_beats),
                    candidates=n_all, candidates_after_byte_limit=len(candidates),
                    skipped_songs=skipped_songs,
                    min_per_mode=args.min_per_mode,
                    mode_shortfall=shortfall,
                    seed_budget=dict(candidates=budget_all, bank=budget_bank)),
        phrases=chosen,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=1) + '\n'
    if len(text.encode('utf-8')) > 60 * 1024:
        text = json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n'
    out.write_text(text, encoding='utf-8', newline='\n')

    print('candidates: %d (%d after the %s-byte limit) | skipped songs: %d' % (
        n_all, len(candidates), args.max_phrase_bytes or 'no', skipped_songs))
    print('chosen:', len(chosen), '| by class:', dict(counts_cls))
    print('by register:', dict(counts_reg))
    print('by mode_hint:', dict(counts_mode))
    print('by beats:', dict(counts_beats))
    print('seed budget (<=%d B) over all candidates: fit %d, over %d' % (
        SEED_BUDGET_BYTES, budget_all['fit'], budget_all['over']))
    for key in ('by_cadence_class', 'by_beats', 'by_mode'):
        print('  %s:' % key, {k: '%d/%d' % (v['fit'], v['fit'] + v['over']) for k, v in sorted(budget_all[key].items())})
    print('seed budget in the bank: fit %d, over %d' % (budget_bank['fit'], budget_bank['over']))
    print('wrote %s (%.1f KB)' % (out, len(text.encode('utf-8')) / 1024.0))
    for m, e in sorted(shortfall.items()):
        print('WARNING: mode shortfall %s: wanted %d, got %d %s' % (m, e['wanted'], e['got'], e['by_cadence_class']))
    if any(counts_cls.get(c, 0) < MIN_PER_CLASS for c in ('sadr', 'ajuz')):
        print('WARNING: fewer than %d phrases in a cadence class' % MIN_PER_CLASS)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
