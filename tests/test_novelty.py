"""Novelty check: every fingerprint variant loads and behaves.

Most tests need only the corpus zip in this repository (the pure estimator in
novelty_check.py is importable without Repo B).  The example-song test needs a
Repo B checkout and skips cleanly without one (see abcsim/repo_b.py).
"""
import importlib.util
import json
import sys
import time
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / 'handoff' / 'skill_0.2.3' / 'scripts' / 'novelty_check.py'
ASSETS = ROOT / 'handoff' / 'skill_0.2.3' / 'assets'
ZIP = ROOT / '670_arabic_songs_abc_scores.zip'
VARIANTS = [ASSETS / 'corpus_fingerprints.bin'] + sorted((ASSETS / 'alt').glob('*.bin'))


def load_nc():
    if not HANDOFF.exists():
        pytest.skip('handoff novelty_check.py is missing')
    spec = importlib.util.spec_from_file_location('novelty_check_under_test', HANDOFF)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def need_variants():
    found = [v for v in VARIANTS if v.exists()]
    if not found:
        pytest.skip('no fingerprint files present')
    return found


def song_prep(nc, sid):
    """prepared n-grams of a corpus song, tokenised with abcsim's own pipeline."""
    if not ZIP.exists():
        pytest.skip('corpus zip is missing')
    from features import song_stream
    from calibrate_novelty import grams_with_starts
    with zipfile.ZipFile(ZIP) as z:
        text = z.read('670_arabic_songs_abc_scores/' + sid).decode('utf-8')
    st = song_stream(text, voice='Vocal')
    assert st is not None, sid
    return nc.prepare(grams_with_starts(st))


def score(nc, prep, entry):
    _sid, hs, tau = entry
    matched, den = nc.match_song(prep, hs, tau)
    if not matched or den <= 0:
        return 0.0
    if tau is not None and len(matched) < nc.MIN_SKETCH_MATCHES:
        return 0.0
    return len(matched) / float(den)


def test_all_variants_load_and_carry_a_threshold():
    nc = load_nc()
    for path in need_variants():
        header, songs = nc.load_bank(path)
        assert header['format'] == 'ABCFP1'
        assert len(songs) == len(header['songs']) > 500
        assert 0.0 < nc.default_threshold(header) < 1.0, path.name
        if header['sketch']:
            assert header['k'] >= 8
            assert all(len(hs) <= header['k'] for _sid, hs, _tau in songs)
            # truncated songs expose tau; complete ones do not
            assert any(tau is not None for _sid, _hs, tau in songs)
        else:
            assert all(tau is None for _sid, _hs, tau in songs)


def known_cluster_pair(nc, full_songs):
    """First (member, representative) pair that overlaps strongly in the full set."""
    clusters = json.loads((ROOT / 'out' / 'clusters.json').read_text(encoding='utf-8'))
    entry = {e[0]: e for e in full_songs}
    for c in sorted(clusters['clusters'], key=lambda c: c['id']):
        rep = c['representative']
        if rep not in entry:
            continue
        for m in c['members']:
            if m['id'] == rep:
                continue
            try:
                prep = song_prep(nc, m['id'])
            except AssertionError:
                continue
            if score(nc, prep, entry[rep]) >= 0.5:
                return m['id'], rep
    pytest.skip('no strongly overlapping cluster pair found')


def test_known_pair_flagged_and_unrelated_pair_not_for_every_variant():
    nc = load_nc()
    variants = need_variants()
    full = next((v for v in variants if not nc.load_bank(v)[0]['sketch']), None)
    if full is None:
        pytest.skip('full-set variant is missing')
    _h, full_songs = nc.load_bank(full)
    member, rep = known_cluster_pair(nc, full_songs)
    # an unrelated pair: two songs from different clusters with no shared n-grams in the full set
    clusters = json.loads((ROOT / 'out' / 'clusters.json').read_text(encoding='utf-8'))
    cluster_of = {m['id']: c['id'] for c in clusters['clusters'] for m in c['members']}
    entry_full = {e[0]: e for e in full_songs}
    q = sorted(entry_full)[0]          # a song that is certainly in the bank
    qprep = song_prep(nc, q)
    unrelated = next(sid for sid in sorted(entry_full)
                     if sid != q and cluster_of.get(sid) != cluster_of.get(q)
                     and score(nc, qprep, entry_full[sid]) < 0.005)
    mprep = song_prep(nc, member)
    for path in variants:
        header, songs = nc.load_bank(path)
        entry = {e[0]: e for e in songs}
        thr = nc.default_threshold(header)
        assert score(nc, mprep, entry[rep]) >= thr, (path.name, member, rep)
        assert score(nc, qprep, entry[unrelated]) < thr, (path.name, q, unrelated)


def test_self_containment_on_kept_song_for_every_variant():
    nc = load_nc()
    keep = (ROOT / 'out' / 'dedupe_keep.txt').read_text(encoding='utf-8').split()
    for path in need_variants():
        header, songs = nc.load_bank(path)
        bank_ids = {s[0] for s in songs}
        sid = next((k for k in keep if k in bank_ids), None)
        if sid is None:
            pytest.skip('no kept song has a fingerprint')
        best = nc.best_match(song_prep(nc, sid), songs)
        assert best is not None and best[2] == sid, path.name
        assert best[0] > 0.9, (path.name, best[0])


def test_sketch_estimator_unit():
    nc = load_nc()
    prep = nc.prepare([(5, 0), (9, 1), (20, 2), (30, 3), (5, 4)])
    # complete song: distinct n-grams {5, 9, 20, 30}; two of them shared -> 0.5
    matched, den = nc.match_song(prep, {5, 9, 99}, None)
    assert (len(matched), den) == (2, 4)
    # sketch with tau=10: only distinct n-grams <= 10 are comparable ({5, 9})
    matched, den = nc.match_song(prep, {5, 9}, 10)
    assert (len(matched), den) == (2, 2)
    # a repeated n-gram counts once (positions do not inflate containment)
    prep = nc.prepare([(7, i) for i in range(100)] + [(8, 100)])
    matched, den = nc.match_song(prep, {7}, None)
    assert (len(matched), den) == (1, 2)


def test_example_song_stays_below_threshold_with_default_bank():
    sys.path.insert(0, str(ROOT / 'abcsim'))
    import repo_b
    rb = repo_b.find_repo_b()
    if rb is None:
        pytest.skip(repo_b.not_found_message())
    example = rb / 'assets' / 'example_song.abc'
    if not example.exists():
        pytest.skip('example_song.abc is missing')
    sys.path.insert(0, str(rb / 'scripts'))
    nc = load_nc()
    bank = ASSETS / 'corpus_fingerprints.bin'
    if not bank.exists():
        pytest.skip('default fingerprint file missing')
    t0 = time.perf_counter()
    line = nc.check(example, bank)
    dt = time.perf_counter() - t0
    assert 'status=ok' in line
    assert dt < 1.0
    assert float(line.split('containment=')[1].split()[0]) < 0.05
