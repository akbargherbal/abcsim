"""
parse.py  --  ABC (SheetSage2 dialect) -> note events.

Turns the text score into plain numbers: for every voice a list of
(onset, midi pitch, duration, bar index), plus the chord symbols.
Time is measured in QUARTER-NOTE BEATS, so the L:1/16 and L:1/32 files
(and any tempo) become comparable.
"""
import re
from dataclasses import dataclass, field
from fractions import Fraction

BASE = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
SHARP_ORDER = ['F', 'C', 'G', 'D', 'A', 'E', 'B']
FLAT_ORDER = ['B', 'E', 'A', 'D', 'G', 'C', 'F']
MAJOR_SHARPS = {'C': 0, 'G': 1, 'D': 2, 'A': 3, 'E': 4, 'B': 5, 'F#': 6, 'C#': 7,
                'F': -1, 'Bb': -2, 'Eb': -3, 'Ab': -4, 'Db': -5, 'Gb': -6, 'Cb': -7}
MINOR_SHARPS = {'A': 0, 'E': 1, 'B': 2, 'F#': 3, 'C#': 4, 'G#': 5, 'D#': 6, 'A#': 7,
                'D': -1, 'G': -2, 'C': -3, 'F': -4, 'Bb': -5, 'Eb': -6, 'Ab': -7}
PC = {'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3, 'E': 4, 'F': 5, 'F#': 6, 'Gb': 6,
      'G': 7, 'G#': 8, 'Ab': 8, 'A': 9, 'A#': 10, 'Bb': 10, 'B': 11, 'Cb': 11}

TOKEN = re.compile(
    r'"(?P<chord>[^"]*)"'
    r'|\[K:(?P<ikey>[^\]]*)\]'
    r'|(?P<acc>[_^=]*)(?P<n>[A-Ga-g])(?P<oct>[\',]*)(?P<len>\d*)(?P<tie>-?)'
    r'|(?P<rest>[zZ])(?P<rlen>\d*)'
    r'|(?P<bar>\|)'
    r'|(?P<other>\S)')


def key_info(k):
    """'Gm' -> (key_signature_dict, tonic_pc, is_minor)"""
    k = k.strip()
    minor = k.endswith('m') and not k.endswith('dim')
    tonic = k[:-1] if minor else k
    tonic = tonic.split()[0]
    n = (MINOR_SHARPS if minor else MAJOR_SHARPS).get(tonic, 0)
    sig = {}
    if n > 0:
        for L in SHARP_ORDER[:n]: sig[L] = 1
    elif n < 0:
        for L in FLAT_ORDER[:-n]: sig[L] = -1
    return sig, PC.get(tonic, 0), minor


@dataclass
class Note:
    onset: float      # quarter-note beats from start of the voice
    midi: int
    dur: float        # quarter-note beats
    bar: int          # bar counter inside the voice (0-based)


@dataclass
class Song:
    key: str = 'C'
    tonic: int = 0
    minor: bool = False
    tempo: float = 100.0
    unit_q: float = 0.25
    voices: dict = field(default_factory=dict)      # name -> [Note]
    chords: list = field(default_factory=list)      # (onset_q, symbol, bar)
    issues: list = field(default_factory=list)      # validator messages
    n_bars: dict = field(default_factory=dict)
    bad_bars: dict = field(default_factory=dict)
    total_q: dict = field(default_factory=dict)


def parse_abc(text):
    s = Song()
    sig = {}
    unit = Fraction(1, 16)
    meter0 = Fraction(4, 4)
    in_body = False
    st = {}                      # per-voice state
    cur = None

    def vs(name):
        if name not in st:
            st[name] = dict(t=0.0, bar_start=0.0, bar=0, acc={}, meter=meter0, tie=None, notes=[], nb=0, bad=0)
        return st[name]

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('%'):
            continue
        m = re.match(r'^([A-Za-z]):\s*(.*)$', line)
        if m and not line.startswith('"'):
            f, v = m.group(1), m.group(2)
            if f == 'L':
                a, b = v.split('/'); unit = Fraction(int(a), int(b))
            elif f == 'M':
                a, b = v.split('/')
                if in_body and cur: vs(cur)['meter'] = Fraction(int(a), int(b))
                else: meter0 = Fraction(int(a), int(b))
            elif f == 'Q':
                mm = re.search(r'=\s*(\d+)', v)
                if mm: s.tempo = float(mm.group(1))
            elif f == 'K':
                s.key = v.strip(); sig, s.tonic, s.minor = key_info(v); in_body = True
            elif f == 'V':
                name = v.split()[0] if v else 'V'
                if in_body: cur = name; vs(cur)
            continue
        if not in_body or cur is None:
            continue
        S = vs(cur)
        unit_q = float(unit) * 4.0
        s.unit_q = unit_q
        for m in TOKEN.finditer(line):
            if m.group('chord') is not None:
                s.chords.append((S['t'], m.group('chord'), S['bar'], cur))
            elif m.group('ikey') is not None:
                sig, s.tonic, s.minor = key_info(m.group('ikey'))
            elif m.group('n'):
                acc, L, octs = m.group('acc'), m.group('n'), m.group('oct')
                n = int(m.group('len')) if m.group('len') else 1
                lo = L.islower(); name = L.upper()
                key = (name, lo, octs)
                if acc:
                    S['acc'][key] = {'^': 1, '_': -1, '=': 0}[acc[-1]]
                shift = S['acc'].get(key, sig.get(name, 0))
                midi = 60 + BASE[name] + (12 if lo else 0) + 12 * octs.count("'") - 12 * octs.count(',') + shift
                d = n * unit_q
                if S['tie'] is not None and S['notes'] and S['notes'][-1].midi == midi:
                    S['notes'][-1].dur += d            # tied: extend previous note
                else:
                    S['notes'].append(Note(S['t'], midi, d, S['bar']))
                S['tie'] = midi if m.group('tie') else None
                S['t'] += d
            elif m.group('rest'):
                n = int(m.group('rlen')) if m.group('rlen') else 1
                if m.group('rest') == 'Z':
                    S['t'] += float(S['meter']) * 4.0 * n
                else:
                    S['t'] += n * unit_q
                S['tie'] = None
            elif m.group('bar'):
                L_ = S['t'] - S['bar_start']
                mq = float(S['meter']) * 4.0
                if L_ > 1e-9:
                    S['nb'] += 1
                    r = L_ / mq
                    if abs(r - round(r)) > 1e-6 or round(r) < 1:
                        S['bad'] += 1
                S['bar_start'] = S['t']; S['bar'] += 1; S['acc'] = {}
            else:
                s.issues.append('unparsed token %r' % m.group('other'))
    for k, S in st.items():
        s.voices[k] = S['notes']; s.n_bars[k] = S['nb']; s.bad_bars[k] = S['bad']; s.total_q[k] = S['t']
    return s


def lead_voice(song, min_notes=20):
    """The voice we treat as 'the melody': most notes (Vocal for songs, Ins for instrumentals)."""
    if not song.voices:
        return None
    name = max(song.voices, key=lambda k: len(song.voices[k]))
    return name if len(song.voices[name]) >= min_notes else None


if __name__ == '__main__':
    import sys
    s = parse_abc(open(sys.argv[1]).read())
    print(s.key, s.tempo, {k: len(v) for k, v in s.voices.items()}, s.bad_bars, s.issues[:3])
