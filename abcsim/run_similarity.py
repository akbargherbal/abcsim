"""run_similarity.py -- all-pairs local alignment. Output: out/pairs_raw.npz (scores + aligned segments)."""
import sys, os, pickle, time
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
from align import sw_many, GAP, MISMATCH
from build_index import build

root = sys.argv[1]; outd = sys.argv[2] if len(sys.argv) > 2 else 'out'; os.makedirs(outd, exist_ok=True)
idx = build(root, os.path.join(outd, 'index.pkl'))
n = len(idx['meta'])
iu = np.triu_indices(n, 1)
pairs = np.stack(iu, 1).astype(np.int64)
res = np.zeros((len(pairs), 5), np.float32)
t0 = time.time(); CH = 4000
for s in range(0, len(pairs), CH):
    res[s:s + CH] = sw_many(idx['ivs'], idx['rcs'], idx['ws'], idx['offs'], pairs[s:s + CH], GAP, MISMATCH)
    if (s // CH) % 5 == 0:
        print('%d/%d  %.0fs' % (s, len(pairs), time.time() - t0), flush=True)
np.savez(os.path.join(outd, 'pairs_raw.npz'), pairs=pairs, res=res)
print('done', time.time() - t0)
