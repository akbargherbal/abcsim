"""run_similarity.py -- all-pairs local alignment.

    python abcsim/run_similarity.py ROOT [OUTD] [--voice lead|vocal|ins]
                                        [--index PATH] [--pairs-out PATH]

Output: OUTD/pairs_raw.npz for lead (default), or OUTD/pairs_raw_<voice>.npz
for vocal/ins.  The index cache follows the same naming scheme.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
from align import sw_many, GAP, MISMATCH
from build_index import build, default_cache


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('root')
    ap.add_argument('outd', nargs='?', default='out')
    ap.add_argument('--voice', choices=['lead', 'vocal', 'ins'], default='lead')
    ap.add_argument('--index', help='override index cache path')
    ap.add_argument('--pairs-out', help='override output .npz path')
    args = ap.parse_args(argv)
    os.makedirs(args.outd, exist_ok=True)

    idx_path = args.index or default_cache(args.outd, args.voice)
    pairs_out = args.pairs_out or os.path.join(
        args.outd, 'pairs_raw.npz' if args.voice == 'lead' else 'pairs_raw_%s.npz' % args.voice)
    idx = build(args.root, idx_path, args.voice)
    n = len(idx['meta'])
    iu = np.triu_indices(n, 1)
    pairs = np.stack(iu, 1).astype(np.int64)
    res = np.zeros((len(pairs), 5), np.float32)
    t0 = time.time(); CH = 4000
    for s in range(0, len(pairs), CH):
        res[s:s + CH] = sw_many(idx['ivs'], idx['rcs'], idx['ws'], idx['offs'], pairs[s:s + CH], GAP, MISMATCH)
        if (s // CH) % 5 == 0:
            print('%d/%d  %.0fs' % (s, len(pairs), time.time() - t0), flush=True)
    np.savez(pairs_out, pairs=pairs, res=res)
    print('done', time.time() - t0, '->', pairs_out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
