#!/usr/bin/env python3
"""novelty_check.py -- advisory corpus-novelty check for a compiled ABC song.

Standard library only.  Put this file in Repo B's scripts/ next to
abc_common.py (the handoff INTEGRATION.md says exactly where).

It parses the compiled song.abc with Repo B's parser, builds the same
interval/rhythm tokens as abcsim.features.tokens_from_notes, hashes 8-token
n-grams with FNV-1a 32, and compares them with the deduped representative
bank.

Containment counts each distinct 8-gram of the composition once.

Prints at most one line:
    NOVELTY closest=suno-0123.abc containment=0.42 matched=18.5 beats status=close

Advisory only: this is a CRAFT-style warning, not a plagiarism verdict.

Usage:
    python novelty_check.py song.abc [--assets ../assets] [--bank FILE] [--threshold T]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from abc_common import parse_abc, parse_key
except ImportError:  # pragma: no cover - only when copied alone
    # The bank readers and the estimator below are pure Python and stay usable
    # (abcsim's calibration and tests import them); parsing a song needs Repo B.
    parse_abc = parse_key = None


def _need_repo_b():
    if parse_abc is None:
        raise SystemExit('novelty_check.py must sit beside abc_common.py')

TOKEN_RE = re.compile(
    r'"(?P<chord>[^"]*)"'
    r'|\[K:(?P<ikey>[^\]]*)\]'
    r"|(?P<acc>[_^=]*)(?P<n>[A-Ga-g])(?P<oct>[\',]*)(?P<len>\d*)(?P<tie>-?)"
    r'|(?P<rest>[zZ])(?P<rlen>\d*)'
    r'|(?P<bar>\|)'
    r'|(?P<other>\S)')

MAGIC = b'ABCFP1\n'
N = 8


# --------------------------------------------------------------------------- tokens
def notes_from_parsed(parsed, voice=None):
    """Reconstruct (onset, midi, dur) notes from Repo B's bar/event parser,
    merging tied notes exactly like abcsim.parse.parse_abc."""
    voices = parsed.get('voices', {})
    if not voices:
        return []
    if voice not in voices:
        voice = 'Vocal' if 'Vocal' in voices else max(
            voices, key=lambda v: sum(1 for bar in voices[v] for ev in bar['events']
                                      if ev['type'] == 'note'))
    out = []
    t = 0.0
    for bar in voices[voice]:
        for ev in bar['events']:
            if ev['type'] == 'note':
                dur = float(ev['dur'])
                if out and out[-1]['tie'] and out[-1]['midi'] == ev['midi']:
                    out[-1]['dur'] += dur
                    out[-1]['tie'] = bool(ev['tie'])
                else:
                    out.append(dict(onset=t, midi=int(ev['midi']), dur=dur,
                                    tie=bool(ev['tie'])))
                t += dur
            else:
                t += float(ev['dur'])
    return out


def tokens_from_notes(notes):
    """Identical arithmetic to abcsim.features.tokens_from_notes (stdlib)."""
    if len(notes) < 4:
        return None
    t = [n['onset'] for n in notes]
    p = [n['midi'] for n in notes]
    ioi = [t[i + 1] - t[i] for i in range(len(t) - 1)]
    ioi = [1e-6 if x <= 1e-6 else x for x in ioi]
    iv = [max(-12, min(12, p[i + 1] - p[i])) for i in range(len(p) - 2)]
    rc = [max(-4, min(4, round(2 * math.log2(ioi[i + 1] / ioi[i]))))
          for i in range(len(ioi) - 1)]
    return iv, rc


def normalize_pitch_dialect(text):
    """Rewrite note accidentals so Repo B's parser yields abcsim's pitches.

    abcsim's cached tokens come from parse.py, which:
      * applies only the last character of an accidental run (^^ -> ^), and
      * follows mid-song K: and inline [K:] key changes.
    Repo B's parser applies double accidentals correctly and uses only the
    first K: signature.  This pass tracks abcsim's key/accidental state and
    writes an explicit accidental on every note, so Repo B's durations, ties,
    bars and onsets are unchanged but the MIDI pitches match the cache.
    """
    _need_repo_b()
    sig = {}
    in_body = False
    cur = None
    states = {}

    def state(name):
        if name not in states:
            states[name] = {'acc': {}}
        return states[name]

    def new_sig(key_text):
        try:
            return parse_key(key_text.strip().split()[0])['signature']
        except Exception:
            return sig

    out_lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('%'):
            out_lines.append(line)
            continue
        m = re.match(r'^([A-Za-z]):\s*(.*)$', line)
        if m and not line.startswith('"'):
            f, v = m.group(1), m.group(2)
            if f == 'K':
                sig = new_sig(v)
                in_body = True
            elif f == 'V':
                cur = v.split()[0] if v.split() else 'V'
                state(cur)
            out_lines.append(line)
            continue
        if not in_body or cur is None:
            out_lines.append(line)
            continue
        st = state(cur)
        parts = []
        last = 0
        for tok in TOKEN_RE.finditer(line):
            parts.append(line[last:tok.start()])
            if tok.group('ikey') is not None:
                sig = new_sig(tok.group('ikey'))
                parts.append(tok.group(0))
            elif tok.group('bar'):
                st['acc'] = {}
                parts.append(tok.group(0))
            elif tok.group('n'):
                letter = tok.group('n')
                name = letter.upper()
                key = (name, letter.islower(), tok.group('oct') or '')
                acc = tok.group('acc') or ''
                if acc:
                    st['acc'][key] = {'^': 1, '_': -1, '=': 0}[acc[-1]]
                desired = st['acc'].get(key, sig.get(name, 0))
                if desired > 0:
                    new_acc = '^' * desired
                elif desired < 0:
                    new_acc = '_' * (-desired)
                else:
                    new_acc = '='
                parts.append(new_acc + letter + (tok.group('oct') or '')
                             + (tok.group('len') or '') + (tok.group('tie') or ''))
            else:
                parts.append(tok.group(0))
            last = tok.end()
        parts.append(line[last:])
        out_lines.append(''.join(parts))
    return '\n'.join(out_lines)


def parse_for_tokens(text):
    _need_repo_b()
    return parse_abc(normalize_pitch_dialect(text), is_text=True)


def tokens_from_text(text, voice=None):
    parsed = parse_for_tokens(text)
    return tokens_from_notes(notes_from_parsed(parsed, voice))


# --------------------------------------------------------------------------- hashes
def hash_ngram(ids):
    h = 2166136261
    for v in ids:
        v = int(v) & 0xFFFF
        h ^= v & 0xFF
        h = (h * 16777619) & 0xFFFFFFFF
        h ^= (v >> 8) & 0xFF
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def composition_grams(tokens):
    iv, rc = tokens
    ids = [(int(a) + 12) * 9 + (int(b) + 4) for a, b in zip(iv, rc)]
    if len(ids) < N:
        return [], ids
    grams = [(hash_ngram(ids[i:i + N]), i) for i in range(len(ids) - N + 1)]
    return grams, ids


# --------------------------------------------------------------------------- bank
DEFAULT_THRESHOLD = 0.05      # full-set bank; sketch banks stamp their own in the header
MIN_SKETCH_MATCHES = 3        # a sketch hit needs at least this many matching n-grams


def load_bank(path):
    """Return (header, songs); songs = [(id, hash_set, tau)].

    tau is None for a complete song.  For a bottom-k sketch that was actually
    truncated (stored count == k) tau is the largest stored hash: the sketch is
    exact for every hash <= tau and knows nothing above it.
    """
    with open(path, 'rb') as f:
        magic = f.read(len(MAGIC))
        if magic != MAGIC:
            raise ValueError('not an ABCFP1 fingerprint file: %s' % path)
        hlen = struct.unpack('<I', f.read(4))[0]
        header = json.loads(f.read(hlen).decode('utf-8'))
        data = f.read()
    count = header['total']
    flat = list(struct.unpack('<%dI' % count, data)) if count else []
    sketch_k = header.get('k', 0) if header.get('sketch') else 0
    songs = []
    for s in header['songs']:
        off, cnt = s['offset'], s['count']
        hs = set(flat[off:off + cnt])
        tau = max(hs) if (sketch_k and cnt >= sketch_k and hs) else None
        songs.append((s['id'], hs, tau))
    return header, songs


def default_threshold(header):
    return float(header.get('threshold', DEFAULT_THRESHOLD))


def prepare(grams):
    """grams = [(hash, position)] -> {hash: [positions]} (each distinct n-gram once).

    This is the one canonical form every matching function below works on.
    """
    by_hash = {}
    for h, i in grams:
        by_hash.setdefault(h, []).append(i)
    return by_hash


def _prepared(prep):
    """Return `prep` in prepared form ({hash: [positions]}).

    Accepts either a prepared dict or the raw [(hash, position)] list that
    composition_grams() returns, so callers cannot pass the wrong shape (the
    raw list used to reach the estimator unconverted and either crashed or
    silently matched nothing).  Anything else is rejected loudly.
    """
    if isinstance(prep, dict):
        return prep
    grams = list(prep)
    if grams and not (isinstance(grams[0], (tuple, list)) and len(grams[0]) == 2):
        raise TypeError('expected prepare() output or [(hash, position)] pairs, got %r'
                        % (grams[0],))
    return prepare(grams)


def match_song(prep, hs, tau):
    """Match a composition against one bank song.

    `prep` is prepare(grams) output (a raw [(hash, position)] list is also
    accepted and prepared here).

    Containment counts each DISTINCT n-gram once: the share of the
    composition's distinct 8-grams that also occur in the bank song.  (Counting
    positions instead lets one repeated riff inflate the score hundreds of
    times; this matches the definition abcsim calibrated against.)

    For a truncated bottom-k sketch only n-grams whose hash is <= tau are
    comparable, so the denominator is the distinct n-grams <= tau (the standard
    bottom-k estimator).  Returns (matched_hashes, denominator).
    """
    prep = _prepared(prep)
    if tau is None:
        den = len(prep)
        return [h for h in prep if h in hs], den
    inr = [h for h in prep if h <= tau]
    return [h for h in inr if h in hs], len(inr)


def matched_positions(prep, matched):
    """Token positions (n-gram start indices) of the matched hashes."""
    prep = _prepared(prep)
    return [i for h in matched for i in prep[h]]


def best_match(prep, songs, tiebreak=None):
    """Return (containment, matched_hashes, song_id) for the closest bank song, or None.

    This is the single ranking routine: check() and the calibration both go
    through it, so the CLI cannot take a different path from the library.

    `tiebreak(matched_hashes)` (optional) ranks songs with equal containment,
    e.g. by matched beats.
    """
    prep = _prepared(prep)
    best = None
    for sid, hs, tau in songs:
        matched, den = match_song(prep, hs, tau)
        if not matched or den <= 0:
            continue
        if tau is not None and len(matched) < MIN_SKETCH_MATCHES:
            continue
        containment = len(matched) / float(den)
        key = (containment, tiebreak(matched) if tiebreak else 0.0)
        if best is None or key > best[0]:
            best = (key, containment, matched, sid)
    if best is None:
        return None
    return best[1], best[2], best[3]


def matched_beats(notes, starts):
    """Union of the time spans covered by matched n-grams (N tokens = N+2 notes)."""
    spans = []
    for i in starts:
        last = min(i + N + 1, len(notes) - 1)
        spans.append((notes[i]['onset'], notes[last]['onset'] + notes[last]['dur']))
    if not spans:
        return 0.0
    spans.sort()
    total = 0.0
    cur_s, cur_e = spans[0]
    for s, e in spans[1:]:
        if s <= cur_e + 1e-9:
            cur_e = max(cur_e, e)
        else:
            total += cur_e - cur_s
            cur_s, cur_e = s, e
    total += cur_e - cur_s
    return total


def beats_tiebreak(notes, prep):
    """Tiebreak for best_match(): matched beats, among songs of equal containment."""
    return lambda matched: matched_beats(notes, matched_positions(prep, matched))


def check(abc_path, bank_path, threshold=None):
    """Return the one-line NOVELTY advisory for a compiled song.

    The only public entry point for the CLI, the skill and the tests.
    """
    text = Path(abc_path).read_text(encoding='utf-8')
    parsed = parse_for_tokens(text)
    notes = notes_from_parsed(parsed, None)
    tokens = tokens_from_notes(notes)
    if tokens is None:
        return 'NOVELTY too-short-to-fingerprint'
    grams, _ids = composition_grams(tokens)
    if not grams:
        return 'NOVELTY too-short-to-fingerprint'
    header, songs = load_bank(bank_path)
    if threshold is None:
        threshold = default_threshold(header)
    prep = prepare(grams)
    # Rank by containment; matched beats break ties among equal containment.
    best = best_match(prep, songs, tiebreak=beats_tiebreak(notes, prep))
    if best is None:
        return 'NOVELTY closest=none containment=0.000 matched=0.0 beats status=ok'
    containment, matched, sid = best
    mb = matched_beats(notes, matched_positions(prep, matched))
    status = 'close' if containment >= threshold else 'ok'
    return 'NOVELTY closest=%s containment=%.3f matched=%.1f beats status=%s' % (
        sid, containment, mb, status)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('abc', help='compiled song.abc')
    ap.add_argument('--assets', help='assets folder (default: ../assets beside this script)')
    ap.add_argument('--threshold', type=float, default=None,
                    help='containment at which the advisory says close '
                         '(default: the value stamped in the bank header, else %.2f)' % DEFAULT_THRESHOLD)
    ap.add_argument('--bank', help='fingerprint file (default: <assets>/corpus_fingerprints.bin)')
    args = ap.parse_args(argv)
    assets = Path(args.assets) if args.assets else Path(__file__).resolve().parent.parent / 'assets'
    bank = Path(args.bank) if args.bank else assets / 'corpus_fingerprints.bin'
    if not bank.exists():
        print('NOVELTY unavailable (missing %s)' % bank)
        return 2
    _need_repo_b()
    print(check(args.abc, bank, args.threshold))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
