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

Size control:
    --budget-bytes N   automatic bottom-k fallback when the full set would exceed N
                       (default 1 MiB)
    --sketch-k K       force a bottom-k sketch of K hashes per song, whatever the budget.
                       A bottom-k sketch keeps the K numerically smallest hashes of a song;
                       header sketch=true and k=K tell readers (novelty_check.py,
                       calibrate_novelty.py) to use the sketch estimator.  Songs with fewer
                       than K hashes are stored complete.

Usage:
    python abcsim/export_fingerprints.py CORPUS_ROOT out
    python abcsim/export_fingerprints.py CORPUS_ROOT out --sketch-k 128 \
        --out handoff/skill_0.2.3/assets/alt/corpus_fingerprints.k128.bin
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


def restamp(path, **fields):
    """Rewrite a fingerprint file's JSON header with extra/updated fields.

    The hash payload is copied untouched (offsets are relative to it), so this
    is how calibrate_novelty --stamp records a variant's threshold.
    """
    path = Path(path)
    raw = path.read_bytes()
    assert raw[:len(MAGIC)] == MAGIC, 'not an ABCFP1 file: %s' % path
    hlen = struct.unpack('<I', raw[len(MAGIC):len(MAGIC) + 4])[0]
    body = len(MAGIC) + 4
    header = json.loads(raw[body:body + hlen].decode('utf-8'))
    payload = raw[body + hlen:]
    header.update(fields)
    hb = json.dumps(header, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    path.write_bytes(MAGIC + struct.pack('<I', len(hb)) + hb + payload)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('corpus', help='folder containing the .abc files')
    ap.add_argument('outd', nargs='?', default='out')
    ap.add_argument('--out', default='handoff/skill_0.2.3/assets/corpus_fingerprints.bin')
    ap.add_argument('--budget-bytes', type=int, default=SIZE_BUDGET,
                    help='automatic bottom-k fallback above this size (default %(default)s)')
    ap.add_argument('--sketch-k', type=int, default=0,
                    help='force a bottom-k sketch of K hashes per song (0 = off)')
    ap.add_argument('--threshold', type=float, default=None,
                    help='stamp an advisory containment threshold into the header '
                         '(novelty_check.py uses it when --threshold is not given)')
    args = ap.parse_args(argv)
    if args.sketch_k < 0 or (0 < args.sketch_k < 8):
        ap.error('--sketch-k must be 0 or at least 8')
    budget = args.budget_bytes

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

    total = sum(len(h) for _, h in per_song)
    header_base = dict(format='ABCFP1', n=N, hash=HASH_NAME,
                       tokenizer='features.tokens_from_notes', sketch=False, k=0,
                       songs=[], total=0, skipped_no_vocal=skipped_no_vocal)

    def est_size(hash_count):
        # header carries one {id, offset, count} record per song
        per = sum(len(json.dumps(dict(id=sid, offset=0, count=0), separators=(',', ':')))
                  for sid, _ in per_song) + 600
        return hash_count * 4 + per + 64

    k = 0
    if args.sketch_k:
        k = args.sketch_k
        print('forced bottom-%d sketch per song' % k)
    elif est_size(total) > budget:
        k = max(32, (budget - est_size(0)) // max(1, len(per_song)) // 4)
        print('size budget %d B: using bottom-%d sketch per song' % (budget, k))
    if k:
        # hs is sorted ascending, so hs[:k] is the bottom-k sketch
        per_song = [(sid, hs[:k]) for sid, hs in per_song]
        header_base['sketch'] = True
        header_base['k'] = k

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
    if args.threshold is not None:
        header['threshold'] = args.threshold
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
    if size > budget:
        print('WARNING: still over the %d B budget' % budget)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
