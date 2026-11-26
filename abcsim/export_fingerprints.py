"""export_fingerprints.py -- 8-gram novelty fingerprints for the kept songs.

Fingerprint definition (matches features.tokens_from_notes):
    token = (interval clipped to +-12, rc = round(2*log2(IOI ratio)) clipped to +-4)
    8-token n-grams, each hashed to 32 bits with FNV-1a, sorted unique per song.

Only the deduped representatives / singletons (out/dedupe_keep.txt) are stored,
and only their Vocal stream.  Songs without a Vocal voice are skipped and
counted.

Output: handoff/skill_0.2.3/assets/corpus_fingerprints.bin
File format: magic b'ABCFP1\\n' + uint32 header length + UTF-8 JSON header +
             little-endian uint32 hashes (per-song slices, sorted unique).

Usage:
    python abcsim/export_fingerprints.py CORPUS_ROOT out
"""
import argparse
import json
import os
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from corpus import load_all
from features import song_stream

MAGIC = b'ABCFP1\n'
N = 8
HASH_NAME = 'fnv1a32'
SIZE_BUDGET = 1024 * 1024


def hash_ngram(ids):
    """FNV-1a over two bytes per token id. Reproducible in stdlib."""
    h = 2166136261
    for v in ids:
        v = int(v) & 0xFFFF
        h ^= v & 0xFF
        h = (h * 16777619) & 0xFFFFFFFF
        h ^= (v >> 8) & 0xFF
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def hashes_for_tokens(iv, rc, n=N):
    if len(iv) < n:
        return []
    ids = (iv.astype(np.int32) + 12) * 9 + (rc.astype(np.int32) + 4)
    out = set()
    for i in range(len(ids) - n + 1):
        out.add(hash_ngram(ids[i:i + n]))
    return sorted(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('corpus', help='folder containing the .abc files')
    ap.add_argument('outd', nargs='?', default='out')
    ap.add_argument('--out', default='handoff/skill_0.2.3/assets/corpus_fingerprints.bin')
    args = ap.parse_args(argv)

    outd = Path(args.outd)
    keep = [x.strip() for x in (outd / 'dedupe_keep.txt').read_text(encoding='utf-8').splitlines()
            if x.strip()]
    keep_set = set(keep)
    songs = {s['id']: s for s in load_all(args.corpus)}

    per_song = []
    skipped_no_vocal = 0
    for sid in keep:
        s = songs.get(sid)
        if s is None:
            skipped_no_vocal += 1
            continue
        st = song_stream(s['abc'], voice='Vocal')
        if st is None:
            skipped_no_vocal += 1
            continue
        hs = hashes_for_tokens(st['iv'], st['rc'], N)
        if not hs:
            skipped_no_vocal += 1
            continue
        per_song.append((sid, hs))

    # bottom-k fallback if the full set would blow the size budget
    total = sum(len(h) for _, h in per_song)
    header_base = dict(format='ABCFP1', n=N, hash=HASH_NAME,
                       tokenizer='features.tokens_from_notes', sketch=False, k=0,
                       songs=[], total=0, skipped_no_vocal=skipped_no_vocal)
    rough = total * 4 + len(json.dumps(header_base, separators=(',', ':')).encode()) + 64
    if rough > SIZE_BUDGET:
        k = max(32, (SIZE_BUDGET - 4096) // max(1, len(per_song)) // 4)
        per_song = [(sid, hs[:k]) for sid, hs in per_song]
        header_base['sketch'] = True
        header_base['k'] = k
        print('size budget: using bottom-%d sketch per song' % k)

    songs_meta = []
    offset = 0
    flat = []
    for sid, hs in per_song:
        songs_meta.append(dict(id=sid, offset=offset, count=len(hs)))
        flat.extend(hs)
        offset += len(hs)
    header = dict(header_base)
    header['songs'] = songs_meta
    header['total'] = len(flat)
    header['note'] = ('Advisory fingerprint only; b5 spelling is irrelevant here, '
                      'tokens are interval/rhythm classes.')
    hb = json.dumps(header, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'wb') as f:
        f.write(MAGIC)
        f.write(struct.pack('<I', len(hb)))
        f.write(hb)
        if flat:
            f.write(np.asarray(flat, dtype='<u4').tobytes())

    size = out.stat().st_size
    print('songs: %d | hashes: %d | avg %.0f | sketch=%s' % (
        len(per_song), len(flat), len(flat) / max(1, len(per_song)), header['sketch']))
    print('skipped (no Vocal / too short): %d' % skipped_no_vocal)
    print('wrote %s (%.2f MB)' % (out, size / (1024.0 * 1024.0)))
    if size > SIZE_BUDGET:
        print('WARNING: still over the 1 MB budget')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
