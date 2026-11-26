"""Phase 1 parity: stats.compute_z must reproduce the old inline calibration.

The old code lived in run_report.py.  We keep a literal copy of it here and
compare on the real out/ data (skipped when the cache is absent).
"""
import os
import pickle
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'abcsim'))

from stats import compute_z, null_model  # noqa: E402

OUT = ROOT / 'out'


def _load():
    if not (OUT / 'index.pkl').exists() or not (OUT / 'pairs_raw.npz').exists():
        pytest.skip('out/index.pkl or out/pairs_raw.npz is missing')
    idx = pickle.load(open(OUT / 'index.pkl', 'rb'))
    d = np.load(OUT / 'pairs_raw.npz')
    return idx, d['pairs'], d['res']


def _old_z(idx, pairs, res):
    """The exact pre-refactor formula from run_report.py."""
    ntok = np.diff(idx['offs'])
    score = res[:, 0].astype(np.float64)
    x = np.log(ntok[pairs[:, 0]] * ntok[pairs[:, 1]].astype(np.float64))
    A = np.vstack([np.ones_like(x), x]).T
    coef, *_ = np.linalg.lstsq(A, score, rcond=None)
    resid = score - A @ coef
    sig = 1.4826 * np.median(np.abs(resid - np.median(resid)))
    z = (resid - np.median(resid)) / sig
    return coef, sig, z


def test_compute_z_matches_old_formula():
    idx, pairs, res = _load()
    coef0, sig0, z0 = _old_z(idx, pairs, res)
    coef1, sig1, z1 = null_model(idx, pairs, res)
    assert np.array_equal(coef0, coef1)
    assert sig0 == sig1
    assert np.array_equal(z0, z1)
    assert np.array_equal(z0, compute_z(idx, pairs, res))


def test_top_pairs_z_column_matches_recomputed():
    idx, pairs, res = _load()
    z = compute_z(idx, pairs, res)
    csv_path = OUT / 'top_pairs.csv'
    if not csv_path.exists():
        pytest.skip('out/top_pairs.csv is missing')
    import csv
    byid = {m['id']: i for i, m in enumerate(idx['meta'])}
    pidx = {(int(a), int(b)): k for k, (a, b) in enumerate(pairs)}
    with open(csv_path, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            a, b = sorted((byid[r['id_A']], byid[r['id_B']]))
            k = pidx[(a, b)]
            assert float(r['z']) == round(float(z[k]), 1)
