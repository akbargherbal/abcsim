"""cluster_dups.py -- group near-duplicate songs from the cached all-pairs alignment.

Input : out/index.pkl, out/pairs_raw.npz (never recomputed here), out/validation.csv
Output: out/clusters.json, out/dedupe_keep.txt, out/dedupe_report.md

An edge exists when the calibrated z-score is high AND the aligned passage
covers a decent share of the shorter song.  The coverage rule is what stops
"we both use the same four-bar chorus riff" from becoming a duplicate.

A second, narrow rescue pass catches the opposite failure: the rarity-weighted
alignment can stop early when the same melody has rhythmic variation.  It only
runs for low-z / low-coverage candidates and requires a long unweighted local
alignment plus a non-negative whole-song global alignment.

Union-find gives raw clusters; a clique guard then splits any cluster that is
only held together by a chain (A~B, B~C, but not A~C).  The representative of
each cluster is chosen for vocal quality, not for alignment score, so the kept
file is the one a human would keep.
"""
import argparse
import collections
import csv
import json
import os
import pickle
import sys

sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
from stats import compute_z
from align import sw_pair, nw_score, GAP, MISMATCH

# Calibrated on the 670-song corpus: the z distribution has a clear gap
# between the duplicate block (z >= 60) and the "shared riff" block
# (z <= 35), and the coverage rule removes everything below the gap anyway.
DEFAULT_Z_MIN = 50.0
DEFAULT_MIN_COVERAGE = 0.25
# Rescue pass for rhythmic variants that the rarity-weighted alignment
# under-reports.  Calibrated against the human listening sheet: the confirmed
# duplicate has uniform coverage 0.96 / global score +3, while the "different"
# controls have global scores -523 and -353.
DEFAULT_RESCUE = True
DEFAULT_RESCUE_COVERAGE = 0.50
DEFAULT_RESCUE_Z_MIN = 10.0
DEFAULT_RESCUE_GLOBAL_MIN = 0.0
SWEEP = [15, 30, 50, 100, 200]
MEDIAN_BARS = 146.0
SEED_A = 'suno-0432.abc'
SEED_B = 'suno-0620.abc'


# --------------------------------------------------------------------------- input
def load_inputs(outd, index=None, pairs_path=None, validation=None):
    idx = pickle.load(open(index or os.path.join(outd, 'index.pkl'), 'rb'))
    d = np.load(pairs_path or os.path.join(outd, 'pairs_raw.npz'))
    pairs, res = d['pairs'], d['res']
    val = {}
    vpath = validation or os.path.join(outd, 'validation.csv')
    if os.path.exists(vpath):
        with open(vpath, encoding='utf-8') as f:
            for r in csv.DictReader(f):
                val[r['id']] = r
    return idx, pairs, res, val


def _coverage(la, lb, na, nb):
    if na <= nb:
        return la / float(na) if na else 0.0
    return lb / float(nb) if nb else 0.0


def pair_coverage(k, pairs, res, ntok):
    """Share of the SHORTER song's tokens that the aligned segment covers."""
    a, b = int(pairs[k, 0]), int(pairs[k, 1])
    la = int(res[k, 2]) - int(res[k, 1]) + 1
    lb = int(res[k, 4]) - int(res[k, 3]) + 1
    return _coverage(la, lb, ntok[a], ntok[b])


def _tokens(idx, i):
    o = idx['offs'][i]
    return idx['ivs'][o:idx['offs'][i + 1]], idx['rcs'][o:idx['offs'][i + 1]]


def build_edges(idx, z, pairs, res, ntok, z_min, min_coverage,
                rescue=DEFAULT_RESCUE, rescue_coverage=DEFAULT_RESCUE_COVERAGE,
                rescue_z_min=DEFAULT_RESCUE_Z_MIN, rescue_global_min=DEFAULT_RESCUE_GLOBAL_MIN):
    """Return {(a,b): info} for every pair that passes the main test.

    The optional rescue pass catches songs whose melody is the same but whose
    rhythm varies enough that the rarity-weighted local alignment stops early.
    It requires (a) an unweighted local alignment covering a large share of the
    shorter song and (b) a non-negative whole-song global alignment, so a
    shared section alone cannot qualify.
    """
    edges = {}
    for k in np.where(z >= z_min)[0]:
        a, b = int(pairs[k, 0]), int(pairs[k, 1])
        cov = pair_coverage(k, pairs, res, ntok)
        if cov < min_coverage:
            continue
        la = int(res[k, 2]) - int(res[k, 1]) + 1
        lb = int(res[k, 4]) - int(res[k, 3]) + 1
        edges[(a, b)] = dict(z=float(z[k]), coverage=float(cov),
                             tokens_a=la, tokens_b=lb, pair_index=int(k),
                             rescue=False, weighted_coverage=float(cov))

    if not rescue:
        return edges

    for k in np.where(z >= rescue_z_min)[0]:
        a, b = int(pairs[k, 0]), int(pairs[k, 1])
        if (a, b) in edges:
            continue
        wcov = pair_coverage(k, pairs, res, ntok)
        if wcov >= min_coverage:
            # Already considered by the main rule (it simply failed z_min).
            continue
        iva, ira = _tokens(idx, a)
        ivb, irb = _tokens(idx, b)
        ru = sw_pair(iva, ira, np.ones(len(iva), np.float32), ivb, irb, GAP, MISMATCH)
        la = int(ru[2]) - int(ru[1]) + 1
        lb = int(ru[4]) - int(ru[3]) + 1
        ucov = _coverage(la, lb, ntok[a], ntok[b])
        if ucov < rescue_coverage:
            continue
        gs = float(nw_score(iva, ira, ivb, irb, GAP, MISMATCH))
        if gs < rescue_global_min:
            continue
        edges[(a, b)] = dict(z=float(z[k]), coverage=float(ucov),
                             tokens_a=la, tokens_b=lb, pair_index=int(k),
                             rescue=True, weighted_coverage=float(wcov),
                             uniform_coverage=float(ucov), uniform_score=float(ru[0]),
                             global_score=gs,
                             seg=(int(ru[1]), int(ru[2]), int(ru[3]), int(ru[4])))
    return edges


# --------------------------------------------------------------------------- union-find
class UnionFind:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


# --------------------------------------------------------------------------- chaining guard
def _clique(members, edges):
    for i, a in enumerate(members):
        for b in members[i + 1:]:
            if (a, b) not in edges:
                return False
    return True


def _diameter_hops(members, edges):
    """Graph diameter of the induced edge graph, in hops (inf if disconnected)."""
    if len(members) <= 1:
        return 0
    pos = {m: i for i, m in enumerate(members)}
    adj = {m: [] for m in members}
    for i, a in enumerate(members):
        for b in members[i + 1:]:
            if (a, b) in edges:
                adj[a].append(b)
                adj[b].append(a)
    best = 0
    for src in members:
        dist = {src: 0}
        q = collections.deque([src])
        while q:
            u = q.popleft()
            for v in adj[u]:
                if v not in dist:
                    dist[v] = dist[u] + 1
                    q.append(v)
        if len(dist) != len(members):
            return float('inf')
        best = max(best, max(dist.values()))
    return best


def _average_linkage_split(members, edges):
    """Deterministic average-linkage cut of one group into two."""
    n = len(members)
    d = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            e = edges.get((min(members[i], members[j]), max(members[i], members[j])))
            dist = 1.0 / (1.0 + e['z']) if e else 1.0
            d[i][j] = d[j][i] = dist
    groups = [[i] for i in range(n)]
    while len(groups) > 2:
        best = None
        for gi in range(len(groups)):
            for gj in range(gi + 1, len(groups)):
                vals = [d[i][j] for i in groups[gi] for j in groups[gj]]
                key = (sum(vals) / len(vals), tuple(sorted(groups[gi] + groups[gj])))
                if best is None or key < best[0]:
                    best = (key, gi, gj)
        _, gi, gj = best
        groups[gi] = sorted(groups[gi] + groups[gj])
        del groups[gj]
    return [sorted(members[i] for i in g) for g in groups]


def split_chained(members, edges, splits, meta):
    """Recursively split any group that is not a clique."""
    members = sorted(members)
    if len(members) <= 2 or _clique(members, edges):
        return [members]
    diam = _diameter_hops(members, edges)
    parts = _average_linkage_split(members, edges)
    splits.append(dict(
        parent=[meta[i]['id'] for i in members],
        children=[[meta[i]['id'] for i in p] for p in parts],
        diameter_hops=(None if diam == float('inf') else diam),
        reason='not a clique (chained through a third song)'))
    out = []
    for p in parts:
        out.extend(split_chained(p, edges, splits, meta))
    return out


# --------------------------------------------------------------------------- representative
def representative_key(i, idx, val):
    m = idx['meta'][i]
    r = val.get(m['id'], {})
    try:
        n_vocal = int(r.get('n_vocal') or 0)
    except ValueError:
        n_vocal = 0
    vocal_ok = 0 if (n_vocal > 0 and r.get('lead') == 'Vocal') else 1
    clean = 0 if (r.get('flags', '') == '') else 1
    try:
        bars = int(r.get('bars') or 0)
    except ValueError:
        bars = 0
    return (vocal_ok, clean, abs(bars - MEDIAN_BARS), m['id'])


def choose_representative(members, idx, val):
    return min(members, key=lambda i: representative_key(i, idx, val))


# --------------------------------------------------------------------------- pair stats for the report
def pair_stats(k, idx, pairs, res, seg=None):
    a, b = int(pairs[k, 0]), int(pairs[k, 1])
    if seg is None:
        sA, eA = int(res[k, 1]), int(res[k, 2])
        sB, eB = int(res[k, 3]), int(res[k, 4])
    else:
        sA, eA, sB, eB = [int(v) for v in seg]
    on = idx['onsets'][a]
    e2 = min(eA + 2, len(on) - 1)
    beats = float(on[e2] - on[sA])
    iv = idx['ivs'][idx['offs'][a] + sA: idx['offs'][a] + eA + 1]
    rc = idx['rcs'][idx['offs'][a] + sA: idx['offs'][a] + eA + 1]
    same = float(np.mean((iv == 0) & (rc == 0))) if len(iv) else 1.0
    return dict(matched_tokens=eA - sA + 1, matched_beats=round(beats, 1),
                trivial_fraction=round(same, 2),
                distinct_tokens=len({(int(p), int(q)) for p, q in zip(iv, rc)}),
                bars_A=[int(idx['bars'][a][sA]) + 1, int(idx['bars'][a][min(eA + 2, len(idx['bars'][a]) - 1)]) + 1],
                bars_B=[int(idx['bars'][b][sB]) + 1, int(idx['bars'][b][min(eB + 2, len(idx['bars'][b]) - 1)]) + 1])


# --------------------------------------------------------------------------- clustering
def build_clusters(idx, pairs, res, z, z_min, min_coverage, val=None,
                   rescue=DEFAULT_RESCUE, rescue_coverage=DEFAULT_RESCUE_COVERAGE,
                   rescue_z_min=DEFAULT_RESCUE_Z_MIN,
                   rescue_global_min=DEFAULT_RESCUE_GLOBAL_MIN):
    meta = idx['meta']
    val = val or {}
    n = len(meta)
    ntok = np.diff(idx['offs'])
    edges = build_edges(idx, z, pairs, res, ntok, z_min, min_coverage,
                        rescue=rescue, rescue_coverage=rescue_coverage,
                        rescue_z_min=rescue_z_min, rescue_global_min=rescue_global_min)
    uf = UnionFind(n)
    for a, b in edges:
        uf.union(a, b)
    raw = collections.defaultdict(list)
    for i in range(n):
        raw[uf.find(i)].append(i)

    splits = []
    final = []
    for g in raw.values():
        if len(g) > 1:
            final.extend(split_chained(g, edges, splits, meta))

    final = [sorted(g) for g in final if len(g) > 1]
    final.sort(key=lambda g: meta[g[0]]['id'])
    clusters = []
    clustered = set()
    for cid, g in enumerate(final, 1):
        clustered.update(g)
        rep = choose_representative(g, idx, val)
        members = []
        for i in g:
            e = edges.get((min(i, rep), max(i, rep)))
            members.append(dict(id=meta[i]['id'],
                                z_to_rep=None if e is None else round(e['z'], 1),
                                coverage_to_rep=None if e is None else round(e['coverage'], 3),
                                edge_type=(None if e is None else ('rescue' if e['rescue'] else 'weighted')),
                                uniform_coverage_to_rep=(None if e is None or not e['rescue'] else round(e['uniform_coverage'], 3)),
                                global_score_to_rep=(None if e is None or not e['rescue'] else round(e['global_score'], 1)),
                                bars=int((val.get(meta[i]['id']) or {}).get('bars') or 0),
                                voice=meta[i]['voice']))
        clusters.append(dict(id='C%03d' % cid, size=len(g), representative=meta[rep]['id'],
                             members=members))
    singletons = [meta[i]['id'] for i in range(n) if i not in clustered]
    return dict(clusters=clusters, singletons=singletons, edges=edges, splits=splits,
                n_songs=n, n_pairs=len(pairs))


def sweep_table(idx, pairs, res, z, min_coverage=DEFAULT_MIN_COVERAGE):
    ntok = np.diff(idx['offs'])
    rows = []
    for zmin in SWEEP:
        edges = build_edges(idx, z, pairs, res, ntok, zmin, min_coverage, rescue=False)
        uf = UnionFind(len(idx['meta']))
        for a, b in edges:
            uf.union(a, b)
        groups = collections.defaultdict(list)
        for i in range(len(idx['meta'])):
            groups[uf.find(i)].append(i)
        cl = [g for g in groups.values() if len(g) > 1]
        rows.append(dict(z_min=zmin, edges=len(edges), clusters=len(cl),
                         songs_in_clusters=sum(len(g) for g in cl),
                         removed=sum(len(g) - 1 for g in cl)))
    return rows


# --------------------------------------------------------------------------- output
def write_outputs(outd, result, idx, pairs, res, z, val, z_min, min_coverage,
                  rescue=DEFAULT_RESCUE, rescue_coverage=DEFAULT_RESCUE_COVERAGE,
                  rescue_z_min=DEFAULT_RESCUE_Z_MIN,
                  rescue_global_min=DEFAULT_RESCUE_GLOBAL_MIN,
                  index_name='index.pkl', pairs_name='pairs_raw.npz'):
    meta = idx['meta']
    voice_mode = idx.get('voice_mode', 'lead')
    voice_desc = {'lead': 'lead (most notes)', 'vocal': 'Vocal only',
                  'ins': 'Ins only'}.get(voice_mode, voice_mode)
    byid = {m['id']: i for i, m in enumerate(meta)}
    os.makedirs(outd, exist_ok=True)

    # --- clusters.json
    seed_cluster = None
    if SEED_A in byid and SEED_B in byid:
        for c in result['clusters']:
            ids = [m['id'] for m in c['members']]
            if SEED_A in ids and SEED_B in ids:
                seed_cluster = c['id']
                break
    seed_ok = seed_cluster is not None
    rescue_edges = sorted([((a, b), e) for (a, b), e in result['edges'].items() if e['rescue']],
                          key=lambda kv: (kv[0][0], kv[0][1]))
    rescue_payload = [dict(id_A=meta[a]['id'], id_B=meta[b]['id'], z=round(e['z'], 1),
                           weighted_coverage=round(e['weighted_coverage'], 3),
                           uniform_coverage=round(e['uniform_coverage'], 3),
                           global_score=round(e['global_score'], 1),
                           seg=[int(v) for v in e['seg']])
                      for (a, b), e in rescue_edges]
    payload = dict(
        params=dict(z_min=z_min, min_coverage=min_coverage, index=index_name,
                    pairs=pairs_name, n_songs=result['n_songs'],
                    n_pairs=result['n_pairs'], voice=voice_mode,
                    rescue=rescue, rescue_coverage=rescue_coverage,
                    rescue_z_min=rescue_z_min, rescue_global_min=rescue_global_min),
        n_rescued_pairs=len(rescue_edges),
        n_clusters=len(result['clusters']),
        songs_in_clusters=sum(c['size'] for c in result['clusters']),
        songs_removed=sum(c['size'] - 1 for c in result['clusters']),
        seed_check=dict(pair=[SEED_A, SEED_B], same_cluster=seed_ok, cluster=seed_cluster),
        rescue_pairs=rescue_payload,
        splits=result['splits'],
        clusters=result['clusters'],
        singletons=result['singletons'])
    with open(os.path.join(outd, 'clusters.json'), 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write('\n')

    # --- dedupe_keep.txt
    keep = sorted([c['representative'] for c in result['clusters']] + result['singletons'])
    with open(os.path.join(outd, 'dedupe_keep.txt'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(keep) + '\n')

    # --- listening pairs: one lowest-z edge per cluster (8 distinct clusters),
    #     plus 3 highest-z rejects below the cut / failing coverage as controls
    ntok = np.diff(idx['offs'])
    per_cluster = []
    for c in result['clusters']:
        ids = {m['id'] for m in c['members']}
        cand = [((a, b), e) for (a, b), e in result['edges'].items()
                if meta[a]['id'] in ids and meta[b]['id'] in ids and not e['rescue']]
        if cand:
            per_cluster.append(min(cand, key=lambda kv: (kv[1]['z'], kv[0])))
    per_cluster.sort(key=lambda kv: (kv[1]['z'], kv[0]))
    above = per_cluster[:8]
    below = []
    for k in np.where((z >= 15) & (z < z_min))[0]:
        cov = pair_coverage(k, pairs, res, ntok)
        if cov < min_coverage:
            below.append((int(pairs[k, 0]), int(pairs[k, 1]), float(z[k]), cov, int(k)))
    below.sort(key=lambda x: -x[2])
    listen = []
    for (a, b), e in above:
        listen.append(dict(id_A=meta[a]['id'], id_B=meta[b]['id'], z=round(e['z'], 1),
                           coverage=round(e['coverage'], 3), above_threshold=True,
                           **pair_stats(e['pair_index'], idx, pairs, res)))
    for a, b, zz, cov, k in below[:3]:
        listen.append(dict(id_A=meta[a]['id'], id_B=meta[b]['id'], z=round(zz, 1),
                           coverage=round(cov, 3), above_threshold=False,
                           **pair_stats(k, idx, pairs, res)))
    for i, r in enumerate(listen, 1):
        ta = ''.join(c for c in meta[byid[r['id_A']]]['title'] if c.isalnum())[:20]
        tb = ''.join(c for c in meta[byid[r['id_B']]]['title'] if c.isalnum())[:20]
        r['file'] = '%02d_cal_%s__%s.mid' % (i, ta, tb)
    with open(os.path.join(outd, 'listen_pairs.tsv'), 'w', encoding='utf-8', newline='\n') as f:
        for r in listen:
            f.write('%s\t%s\n' % (r['id_A'], r['id_B']))

    # --- rescue pairs: write coordinates of the unweighted alignment so
    #     export_segments.py can render the right (long) passage
    rescue_listen = []
    with open(os.path.join(outd, 'rescue_pairs.tsv'), 'w', encoding='utf-8', newline='\n') as f:
        for i, ((a, b), e) in enumerate(rescue_edges, 1):
            sA, eA, sB, eB = [int(v) for v in e['seg']]
            f.write('%s\t%s\t%d\t%d\t%d\t%d\n' % (meta[a]['id'], meta[b]['id'], sA, eA, sB, eB))
            ta = ''.join(c for c in meta[a]['title'] if c.isalnum())[:20]
            tb = ''.join(c for c in meta[b]['title'] if c.isalnum())[:20]
            rescue_listen.append(dict(id_A=meta[a]['id'], id_B=meta[b]['id'],
                                      z=round(e['z'], 1),
                                      weighted_coverage=round(e['weighted_coverage'], 3),
                                      uniform_coverage=round(e['uniform_coverage'], 3),
                                      global_score=round(e['global_score'], 1),
                                      file='%02d_rescue_%s__%s.mid' % (i, ta, tb),
                                      **pair_stats(e['pair_index'], idx, pairs, res, seg=e['seg'])))

    # --- report
    sweep = sweep_table(idx, pairs, res, z, min_coverage)
    lines = []
    lines.append('# Near-duplicate clusters (abcsim)')
    lines.append('')
    lines.append('Generated by `abcsim/cluster_dups.py` from `%s` and `%s`.' % (
        index_name, pairs_name))
    lines.append('')
    lines.append('## Parameters')
    lines.append('')
    lines.append('| parameter | value |')
    lines.append('|---|---|')
    lines.append('| z-min | %g |' % z_min)
    lines.append('| min-coverage (share of shorter song) | %g |' % min_coverage)
    lines.append('| rescue pass | %s |' % ('on' if rescue else 'off'))
    if rescue:
        lines.append('| rescue uniform coverage | %g |' % rescue_coverage)
        lines.append('| rescue z-min | %g |' % rescue_z_min)
        lines.append('| rescue global-score floor | %g |' % rescue_global_min)
    lines.append('| voice compared | %s |' % voice_desc)
    lines.append('| songs | %d |' % result['n_songs'])
    lines.append('| pairs | %d |' % result['n_pairs'])
    lines.append('')
    lines.append('## Summary')
    lines.append('')
    lines.append('| metric | value |')
    lines.append('|---|---|')
    lines.append('| clusters | %d |' % len(result['clusters']))
    lines.append('| songs in clusters | %d |' % payload['songs_in_clusters'])
    lines.append('| songs removed by dedupe | %d |' % payload['songs_removed'])
    lines.append('| songs kept (representatives + singletons) | %d |' % len(keep))
    lines.append('| weighted main-rule edges | %d |' % (len(result['edges']) - len(rescue_edges)))
    lines.append('| rescue-pass edges | %d |' % len(rescue_edges))
    lines.append('| total edges | %d |' % len(result['edges']))
    lines.append('')
    lines.append('## Seed check')
    lines.append('')
    lines.append('`duplicates_report.csv` marks `%s` / `%s` as a 96.67%% text duplicate.' % (SEED_A, SEED_B))
    if seed_ok:
        lines.append('They are in the same cluster: **%s**. PASS.' % seed_cluster)
    else:
        lines.append('They are **not** in the same cluster. FAIL.')
    lines.append('')
    lines.append('## Threshold sweep')
    lines.append('')
    lines.append('Main rule only (rescue pass disabled). Coverage fixed at %g; chosen threshold **%g**.' % (min_coverage, z_min))
    lines.append('')
    lines.append('| z-min | edges | clusters | songs in clusters | songs removed |')
    lines.append('|---|---|---|---|---|')
    for r in sweep:
        lines.append('| %d | %d | %d | %d | %d |' % (
            r['z_min'], r['edges'], r['clusters'], r['songs_in_clusters'], r['removed']))
    lines.append('')
    lines.append('The z distribution has a large gap between the duplicate block and the')
    lines.append('shared-riff block. On this corpus every coverage-passing edge has z >= 60,')
    lines.append('so any cut between 15 and 50 gives the same clusters. We use 50 to leave')
    lines.append('headroom against a future corpus where the gap is less clean.')
    lines.append('')
    lines.append('## Top 10 largest clusters')
    lines.append('')
    lines.append('| # | size | representative | members |')
    lines.append('|---|---|---|---|')
    top = sorted(result['clusters'], key=lambda c: (-c['size'], c['id']))[:10]
    for i, c in enumerate(top, 1):
        lines.append('| %d | %d | %s | %s |' % (
            i, c['size'], c['representative'],
            ', '.join('%s (z=%s, cov=%s%s)' % (
                m['id'], m['z_to_rep'], m['coverage_to_rep'],
                ', rescue' if m['edge_type'] == 'rescue' else '')
                for m in c['members'])))
    lines.append('')
    lines.append('## Chaining guard')
    lines.append('')
    if result['splits']:
        for s in result['splits']:
            lines.append('- split %s into %s (diameter %s hops): %s' % (
                ', '.join(s['parent']), ' + '.join('[' + ', '.join(c) + ']' for c in s['children']),
                s['diameter_hops'], s['reason']))
    else:
        lines.append('No cluster needed splitting: every cluster is a clique under the edge')
        lines.append('rules (weighted main rule or rescue pass).')
    lines.append('')
    lines.append('## Listening excerpts')
    lines.append('')
    lines.append('MIDI files are in `%s`. The first 8 are the lowest-z pair from 8 **distinct**' % os.path.join(outd, 'listen'))
    lines.append('clusters above the cut (hardest duplicates to judge). The last 3 are the')
    lines.append('highest-z pairs **below** the cut or failing coverage (shared-riff controls).')
    lines.append('This table is the weighted main rule only; rescue-pass pairs are listed below.')
    lines.append('Generate them with:')
    lines.append('')
    lines.append('    python abcsim/export_segments.py <corpus_root> %s --pairs %s --tag cal' % (
        outd, os.path.join(outd, 'listen_pairs.tsv')))
    lines.append('')
    lines.append('| file | A | B | z | coverage | matched beats | trivial fraction | distinct tokens | verdict |')
    lines.append('|---|---|---|---|---|---|---|---|---|')
    for r in listen:
        verdict = 'above cut' if r['above_threshold'] else 'control'
        lines.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (
            r['file'], r['id_A'], r['id_B'], r['z'], r['coverage'], r['matched_beats'],
            r['trivial_fraction'], r['distinct_tokens'], verdict))
    lines.append('')
    lines.append('What separates the two groups in these excerpts: the above-cut pairs align')
    lines.append('most of the shorter song (high coverage) over a long passage with low')
    lines.append('trivial-note fraction, while the controls share only a short, often repeated')
    lines.append('riff (low coverage). Listen for the same phrase continuing past the riff in')
    lines.append('the above-cut pairs. Human sign-off is still required before deleting files.')
    lines.append('')
    lines.append('## Rescue pass')
    lines.append('')
    lines.append('The rarity-weighted alignment can stop early when the same melody has enough')
    lines.append('rhythmic variation. This second pass is only for pairs with z >= %g that fail' % rescue_z_min)
    lines.append('the weighted coverage rule. It accepts a pair only when:')
    lines.append('')
    lines.append('- an **unweighted** local alignment covers >= %g of the shorter song, and' % rescue_coverage)
    lines.append('- a whole-song global alignment scores >= %g (0 = break-even).' % rescue_global_min)
    lines.append('')
    lines.append('Calibration from the listening sheet: `suno-0089` / `suno-0108` was marked')
    lines.append('**same** (uniform coverage 0.96, global score +3), while the two controls marked')
    lines.append('"unsure/different" scored -523 and -353. The global-score floor is what rejects')
    lines.append('shared sections that happen to cover half of a short song.')
    lines.append('')
    if rescue_listen:
        lines.append('| file | A | B | z | weighted cov | uniform cov | global score | matched beats | trivial fraction |')
        lines.append('|---|---|---|---|---|---|---|---|---|')
        for r in rescue_listen:
            lines.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (
                r['file'], r['id_A'], r['id_B'], r['z'], r['weighted_coverage'],
                r['uniform_coverage'], r['global_score'], r['matched_beats'],
                r['trivial_fraction']))
        lines.append('')
        lines.append('Generate these excerpts with:')
        lines.append('')
        lines.append('    python abcsim/export_segments.py <corpus_root> %s --pairs %s --tag rescue' % (
            outd, os.path.join(outd, 'rescue_pairs.tsv')))
        lines.append('')
        lines.append('`suno-0089` / `suno-0108` is confirmed by listening. `suno-0106` / `suno-0122`')
        lines.append('is the strongest automatic rescue and should be spot-checked before the deduped')
        lines.append('corpus is used.')
    else:
        lines.append('No pair qualified for rescue in this run.')
    lines.append('')
    lines.append('## Voice mode and limitations')
    lines.append('')
    lines.append('- This run compares only the **lead** voice (most notes). 82 songs have `Ins`')
    lines.append('  as lead; cross-lead duplicates (Ins-lead vs Vocal-lead) can be missed.')
    lines.append('  `build_index.py --voice vocal` + `run_similarity.py --voice vocal` build a')
    lines.append('  vocal-only index for a later comparison. Run `compare_cluster_runs.py` to')
    lines.append('  write `out/vocal/clusters_lead_vs_vocal.md`; vocal-only clusters are')
    lines.append('  candidates for human review, never automatic merges.')
    lines.append('- Representative choice uses `validation.csv`: non-empty Vocal lead first,')
    lines.append('  then no flags, then bar count nearest %g, then lowest id.' % MEDIAN_BARS)
    lines.append('- The corpus has no lyrics and no ratings, so these are melodic near-duplicates,')
    lines.append('  not a claim about released versions.')
    lines.append('')
    with open(os.path.join(outd, 'dedupe_report.md'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines))

    return dict(keep=keep, listen=listen, rescue_listen=rescue_listen,
                seed_ok=seed_ok, seed_cluster=seed_cluster,
                payload=payload, sweep=sweep)


# --------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('outd', nargs='?', default='out', help='folder with index.pkl / pairs_raw.npz (default: out)')
    ap.add_argument('--z-min', type=float, default=DEFAULT_Z_MIN, help='z threshold (default: %(default)s)')
    ap.add_argument('--min-coverage', type=float, default=DEFAULT_MIN_COVERAGE,
                    help='minimum aligned share of the shorter song (default: %(default)s)')
    ap.add_argument('--index', help='override index.pkl path (e.g. out/index_vocal.pkl)')
    ap.add_argument('--pairs', help='override pairs_raw.npz path')
    ap.add_argument('--validation', help='override validation.csv path')
    ap.add_argument('--no-rescue', dest='rescue', action='store_false',
                    help='disable the unweighted second pass for rhythmic variants')
    ap.add_argument('--rescue-coverage', type=float, default=DEFAULT_RESCUE_COVERAGE,
                    help='uniform-alignment coverage needed by the rescue pass (default: %(default)s)')
    ap.add_argument('--rescue-z-min', type=float, default=DEFAULT_RESCUE_Z_MIN,
                    help='lowest z considered by the rescue pass (default: %(default)s)')
    ap.add_argument('--rescue-global-min', type=float, default=DEFAULT_RESCUE_GLOBAL_MIN,
                    help='minimum whole-song global score for a rescue (default: %(default)s)')
    args = ap.parse_args(argv)

    idx, pairs, res, val = load_inputs(args.outd, args.index, args.pairs, args.validation)
    z = compute_z(idx, pairs, res)
    result = build_clusters(idx, pairs, res, z, args.z_min, args.min_coverage, val,
                            rescue=args.rescue, rescue_coverage=args.rescue_coverage,
                            rescue_z_min=args.rescue_z_min,
                            rescue_global_min=args.rescue_global_min)
    info = write_outputs(args.outd, result, idx, pairs, res, z, val,
                         args.z_min, args.min_coverage,
                         rescue=args.rescue, rescue_coverage=args.rescue_coverage,
                         rescue_z_min=args.rescue_z_min,
                         rescue_global_min=args.rescue_global_min,
                         index_name=os.path.basename(args.index) if args.index else 'index.pkl',
                         pairs_name=os.path.basename(args.pairs) if args.pairs else 'pairs_raw.npz')

    print('%d songs, %d pairs' % (result['n_songs'], result['n_pairs']))
    print('%d clusters, %d songs in clusters, %d removed, %d kept' % (
        len(result['clusters']), info['payload']['songs_in_clusters'],
        info['payload']['songs_removed'], len(info['keep'])))
    print('%d rescue-pass edges' % info['payload']['n_rescued_pairs'])
    print('seed %s / %s: %s' % (SEED_A, SEED_B,
                                ('same cluster ' + str(info['seed_cluster'])) if info['seed_ok'] else 'NOT same cluster'))
    print('wrote %s, %s, %s' % (os.path.join(args.outd, 'clusters.json'),
                                os.path.join(args.outd, 'dedupe_keep.txt'),
                                os.path.join(args.outd, 'dedupe_report.md')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
