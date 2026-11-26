"""stats.py -- shared calibration of raw alignment scores.

The raw Smith-Waterman score grows roughly like log(nA * nB) (longer token
streams can accumulate longer alignments even when unrelated).  We fit that
null model by least squares and turn every residual into a robust z-score:

    z = (resid - median(resid)) / (1.4826 * MAD(resid))

Both run_report.py and the newer dedup / phrase / fingerprint scripts use
this so that a "z >= threshold" decision means the same thing everywhere.
"""
import numpy as np


def null_model(idx, pairs, res):
    """Fit score ~ log(nA*nB) on the given pairs.

    Returns (coef, sigma, z) where coef is the length-2 least-squares
    coefficient vector, sigma is the robust MAD scale, and z is one robust
    z-score per pair.  Kept separate from compute_z so callers that print the
    calibration (run_report.py) do not have to refit.
    """
    ntok = np.diff(idx['offs'])
    score = res[:, 0].astype(np.float64)
    x = np.log(ntok[pairs[:, 0]] * ntok[pairs[:, 1]].astype(np.float64))
    A = np.vstack([np.ones_like(x), x]).T
    coef, *_ = np.linalg.lstsq(A, score, rcond=None)
    resid = score - A @ coef
    med = np.median(resid)
    sig = 1.4826 * np.median(np.abs(resid - med))
    if sig <= 0:
        sig = 1.0
    z = (resid - med) / sig
    return coef, sig, z


def compute_z(idx, pairs, res):
    """Robust z-score of every pair's raw score against the log-length null."""
    return null_model(idx, pairs, res)[2]
