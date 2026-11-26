"""align.py -- Smith-Waterman local alignment on (interval, rhythm-ratio) tokens, weighted by rarity."""
import numpy as np
from numba import njit

GAP = 1.2
MISMATCH = 1.0


@njit(cache=True, fastmath=True)
def sw_pair(iva, rca, wa, ivb, rcb, gap, mis):
    n = len(iva); m = len(ivb)
    Hp = np.zeros(m + 1, np.float32); Hc = np.zeros(m + 1, np.float32)
    Sip = np.zeros(m + 1, np.int32); Sjp = np.zeros(m + 1, np.int32)
    Sic = np.zeros(m + 1, np.int32); Sjc = np.zeros(m + 1, np.int32)
    best = 0.0; bi = 0; bj = 0; bsi = 0; bsj = 0
    for i in range(1, n + 1):
        Hc[0] = 0.0
        a_i = iva[i - 1]; a_r = rca[i - 1]; w = wa[i - 1]
        for j in range(1, m + 1):
            di = a_i - ivb[j - 1]; dr = a_r - rcb[j - 1]
            if di == 0 and dr == 0:
                s = w
            elif di == 0 and (dr == 1 or dr == -1):
                s = 0.4 * w
            elif dr == 0 and (di == 1 or di == -1):
                s = 0.3 * w
            else:
                s = -mis
            h = 0.0; si = i; sj = j
            d = Hp[j - 1] + s
            if d > h:
                h = d
                if Hp[j - 1] > 0: si = Sip[j - 1]; sj = Sjp[j - 1]
            u = Hp[j] - gap
            if u > h:
                h = u; si = Sip[j]; sj = Sjp[j]
            l = Hc[j - 1] - gap
            if l > h:
                h = l; si = Sic[j - 1]; sj = Sjc[j - 1]
            Hc[j] = h; Sic[j] = si; Sjc[j] = sj
            if h > best:
                best = h; bi = i; bj = j; bsi = si; bsj = sj
        for j in range(m + 1):
            Hp[j] = Hc[j]; Sip[j] = Sic[j]; Sjp[j] = Sjc[j]
    return best, bsi - 1, bi - 1, bsj - 1, bj - 1


@njit(cache=True)
def sw_many(ivs, rcs, ws, offs, pairs, gap, mis):
    P = len(pairs)
    out = np.zeros((P, 5), np.float32)
    for k in range(P):
        a = pairs[k, 0]; b = pairs[k, 1]
        r = sw_pair(ivs[offs[a]:offs[a + 1]], rcs[offs[a]:offs[a + 1]], ws[offs[a]:offs[a + 1]],
                    ivs[offs[b]:offs[b + 1]], rcs[offs[b]:offs[b + 1]], gap, mis)
        out[k, 0] = r[0]; out[k, 1] = r[1]; out[k, 2] = r[2]; out[k, 3] = r[3]; out[k, 4] = r[4]
    return out


def token_weights(all_iv, all_rc):
    """rarity weight per token: common tokens (repeated notes, same-rhythm steps) are worth less."""
    tid = (all_iv.astype(np.int32) + 12) * 9 + (all_rc.astype(np.int32) + 4)
    cnt = np.bincount(tid, minlength=25 * 9).astype(np.float64) + 1
    p = cnt / cnt.sum()
    w = np.clip(-np.log2(p) / 6.0, 0.15, 1.5).astype(np.float32)
    return w
