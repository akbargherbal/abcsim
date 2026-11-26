"""Phase 2 seed: the known text duplicate pair must share a cluster.

Also checks reproducibility (same inputs -> same clusters) and that the seed
pair contributes exactly one kept file.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'abcsim'))

from stats import compute_z  # noqa: E402
import cluster_dups  # noqa: E402

OUT = ROOT / 'out'
SEED = {'suno-0432.abc', 'suno-0620.abc'}


def _run():
    if not (OUT / 'index.pkl').exists() or not (OUT / 'pairs_raw.npz').exists():
        pytest.skip('out/index.pkl or out/pairs_raw.npz is missing')
    idx, pairs, res, val = cluster_dups.load_inputs(str(OUT))
    z = compute_z(idx, pairs, res)
    return idx, pairs, res, val, z


def _cluster_of(result, song_id):
    for c in result['clusters']:
        if song_id in {m['id'] for m in c['members']}:
            return c
    return None


def test_seed_pair_same_cluster():
    idx, pairs, res, val, z = _run()
    result = cluster_dups.build_clusters(idx, pairs, res, z, 50.0, 0.25, val)
    a = _cluster_of(result, 'suno-0432.abc')
    b = _cluster_of(result, 'suno-0620.abc')
    assert a is not None and b is not None
    assert a['id'] == b['id']
    ids = {m['id'] for m in a['members']}
    assert SEED <= ids
    reps = [c['representative'] for c in result['clusters']]
    assert len([r for r in reps if r in SEED]) == 1


def test_clusters_reproducible():
    idx, pairs, res, val, z = _run()
    r1 = cluster_dups.build_clusters(idx, pairs, res, z, 50.0, 0.25, val)
    r2 = cluster_dups.build_clusters(idx, pairs, res, z, 50.0, 0.25, val)
    fields = ('clusters', 'singletons', 'splits', 'n_songs', 'n_pairs')
    a = {k: r1[k] for k in fields}
    b = {k: r2[k] for k in fields}
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_rescue_pairs():
    """The listening-confirmed rhythmic variant and the strong automatic one."""
    idx, pairs, res, val, z = _run()
    result = cluster_dups.build_clusters(idx, pairs, res, z, 50.0, 0.25, val)
    for a_id, b_id in [('suno-0089.abc', 'suno-0108.abc'),
                       ('suno-0106.abc', 'suno-0122.abc')]:
        a = _cluster_of(result, a_id)
        b = _cluster_of(result, b_id)
        assert a is not None and b is not None
        assert a['id'] == b['id']
    # Shared-section candidates must stay out of the same cluster.
    for a_id, b_id in [('suno-0112.abc', 'suno-0177.abc'),
                       ('suno-0111.abc', 'suno-0175.abc'),
                       ('suno-0069.abc', 'suno-0070.abc'),
                       ('suno-0070.abc', 'suno-0122.abc')]:
        a = _cluster_of(result, a_id)
        b = _cluster_of(result, b_id)
        assert a is None or b is None or a['id'] != b['id']


def test_keep_file_is_written_and_consistent():
    idx, pairs, res, val, z = _run()
    result = cluster_dups.build_clusters(idx, pairs, res, z, 50.0, 0.25, val)
    info = cluster_dups.write_outputs(str(OUT), result, idx, pairs, res, z, val, 50.0, 0.25)
    keep = (OUT / 'dedupe_keep.txt').read_text(encoding='utf-8').split()
    assert len(keep) == len(info['keep'])
    assert len(keep) == len(set(keep))
    assert sum(1 for s in SEED if s in keep) == 1
