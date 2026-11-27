"""Novelty check: every fingerprint variant loads and behaves.

Most tests need only the corpus zip in this repository (the pure estimator in
novelty_check.py is importable without Repo B).  The negative controls that use
Repo B's example song need a Repo B checkout and skip cleanly without one (see
abcsim/repo_b.py).

The end-to-end controls call novelty_check.check() -- the one entry point the
CLI and the skill use -- on every bank variant.  With a Repo B checkout they use
Repo B's real parser.  Without one they still run: the two parsing hooks of the
module under test are pointed at abcsim's own parser, so everything after
parsing (bank loading, matching, ranking, thresholds, formatting) is the real
check() code.
"""
import importlib.util
import json
import shutil
import subprocess
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


EXPECTED_THRESHOLDS = {            # the threshold stamped in each file header
    'corpus_fingerprints.bin': 0.08,
    'corpus_fingerprints.full.bin': 0.08,
    'corpus_fingerprints.k512.bin': 0.08,
    'corpus_fingerprints.k128.bin': 0.15,
    'corpus_fingerprints.k64.bin': 0.15,
}
SKETCH_VARIANTS = [n for n in EXPECTED_THRESHOLDS if n not in
                   ('corpus_fingerprints.bin', 'corpus_fingerprints.full.bin')] + ['corpus_fingerprints.bin']
CONTROL_SONG = 'suno-0100.abc'     # a corpus song that is in every bank


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


# =========================================================================== end-to-end
# Regression tests for the check() / match_song() input-shape bug: check() used to
# hand match_song() raw (hash, position) tuples, which crashed every sketch bank and
# silently matched nothing on the full bank.

def _variant_ids():
    return [n for n in EXPECTED_THRESHOLDS]


def _bank_path(name):
    path = ASSETS / name if name == 'corpus_fingerprints.bin' else ASSETS / 'alt' / name
    assert path.exists(), 'handoff asset is missing: %s' % path
    return path


def _abcsim_notes_from_parsed(song, voice=None):
    """Stand-in for novelty_check.notes_from_parsed using abcsim's own parser output."""
    voices = song.voices
    v = 'Vocal' if 'Vocal' in voices else max(voices, key=lambda k: len(voices[k]))
    return [dict(onset=float(n.onset), midi=int(n.midi), dur=float(n.dur), tie=False)
            for n in voices[v]]


def load_checker():
    """(module, backend) where module.check() can parse a song file.

    backend is 'repo_b' (Repo B's real parser) or 'abcsim' (abcsim's parser behind
    the same two hooks, used when no Repo B checkout is available)."""
    sys.path.insert(0, str(ROOT / 'abcsim'))
    import repo_b
    rb = repo_b.find_repo_b()
    if rb is not None:
        sys.path.insert(0, str(rb / 'scripts'))
        return load_nc(), 'repo_b'
    from parse import parse_abc
    nc = load_nc()
    nc.parse_for_tokens = parse_abc
    nc.notes_from_parsed = _abcsim_notes_from_parsed
    return nc, 'abcsim'


def repo_b_example():
    sys.path.insert(0, str(ROOT / 'abcsim'))
    import repo_b
    rb = repo_b.find_repo_b()
    if rb is None:
        pytest.skip(repo_b.not_found_message())
    example = rb / 'assets' / 'example_song.abc'
    if not example.exists():
        pytest.skip('example_song.abc is missing')
    return rb, example


def corpus_text(sid):
    if not ZIP.exists():
        pytest.skip('corpus zip is missing')
    with zipfile.ZipFile(ZIP) as z:
        return z.read('670_arabic_songs_abc_scores/' + sid).decode('utf-8')


def vocal_parts(text):
    """(header lines through K:, Vocal music lines) of a corpus ABC file."""
    lines = text.splitlines()
    header = []
    k = 0
    for k, line in enumerate(lines):
        header.append(line)
        if line.startswith('K:'):
            break
    voice, music = None, []
    for line in lines[k + 1:]:
        if line.startswith('V:'):
            voice = line[2:].split()[0]
        elif voice == 'Vocal' and line.strip() and not line.startswith('%'):
            music.append(line)
    return header, music


def build_abc(header, music_lines):
    return '\n'.join(header + ['V: Vocal'] + music_lines) + '\n'


def novel_filler(n_lines):
    """Deterministic made-up melody (own LCG, so identical on every Python version)."""
    state = [12345]

    def rnd(n):
        state[0] = (state[0] * 1103515245 + 12345) & 0x7FFFFFFF
        return (state[0] >> 8) % n

    letters = 'ABCDEFGabcdefg'
    durs = [2, 2, 4, 1, 3, 6]
    out = []
    for _ in range(n_lines):
        bars = []
        for _b in range(4):
            total, ev = 0, []
            while total < 16:
                d = min(durs[rnd(len(durs))], 16 - total)
                total += d
                ev.append(letters[rnd(len(letters))] + (str(d) if d != 1 else ''))
            bars.append(''.join(ev))
        out.append('|'.join(bars) + '|')
    return out


def write_abc(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding='utf-8', newline='\n')
    return path


def parse_line(line):
    """NOVELTY closest=X containment=C matched=M beats status=S -> dict."""
    assert line.startswith('NOVELTY closest='), line
    f = dict(tok.split('=', 1) for tok in line.split() if '=' in tok)
    return dict(closest=f['closest'], containment=float(f['containment']),
                matched=float(f['matched']), status=f['status'])


def control_inputs(tmp_path):
    """Three corpus-derived inputs: the whole song, a vocal excerpt, and a splice of
    14 copied lines among novel filler (containment ~0.1: between the two thresholds)."""
    header, music = vocal_parts(corpus_text(CONTROL_SONG))
    filler = novel_filler(60)
    return {
        'whole': write_abc(tmp_path, 'whole.abc', corpus_text(CONTROL_SONG)),
        'excerpt': write_abc(tmp_path, 'excerpt.abc', build_abc(header, music[:len(music) // 2])),
        'splice': write_abc(tmp_path, 'splice.abc',
                            build_abc(header, filler[:30] + music[20:34] + filler[30:])),
    }


def test_all_five_banks_are_present():
    assert (ASSETS / 'corpus_fingerprints.bin').exists()
    alt = {p.name for p in (ASSETS / 'alt').glob('*.bin')}
    assert alt == {n for n in EXPECTED_THRESHOLDS if n != 'corpus_fingerprints.bin'}


@pytest.mark.parametrize('name', _variant_ids())
@pytest.mark.parametrize('which', ['whole', 'excerpt'])
def test_positive_control_corpus_song_is_close_on_every_bank(name, which, tmp_path):
    """An unmodified corpus song (or an excerpt of one) is in the bank: it must say close."""
    nc, _backend = load_checker()
    path = control_inputs(tmp_path)[which]
    line = nc.check(path, _bank_path(name))          # header threshold, no override
    r = parse_line(line)
    assert r['status'] == 'close', (name, which, line)
    assert r['closest'] == CONTROL_SONG, (name, which, line)
    assert r['containment'] > 0.9, (name, which, line)
    assert r['matched'] > 0.0, (name, which, line)


@pytest.mark.parametrize('name', _variant_ids())
def test_negative_control_repo_b_example_is_ok_on_every_bank(name):
    nc, _backend = load_checker()
    _rb, example = repo_b_example()
    line = nc.check(example, _bank_path(name))
    assert 'status=ok' in line, (name, line)
    assert parse_line(line)['containment'] < EXPECTED_THRESHOLDS[name]


def test_check_raises_nothing_on_any_bank(tmp_path):
    nc, _backend = load_checker()
    inputs = list(control_inputs(tmp_path).values())
    try:
        inputs.append(repo_b_example()[1])
    except pytest.skip.Exception:
        pass
    failures = []
    for name in _variant_ids():
        for path in inputs:
            try:
                line = nc.check(path, _bank_path(name))
                assert line.startswith('NOVELTY '), line
            except Exception as exc:                  # noqa: BLE001 - report every failure
                failures.append((name, Path(path).name, '%s: %s' % (type(exc).__name__, exc)))
    assert not failures, failures


def test_check_and_best_match_agree_on_sketch_banks(tmp_path):
    """check() and best_match() must pick the same closest song with the same containment."""
    nc, _backend = load_checker()
    inputs = control_inputs(tmp_path)
    try:
        inputs['example'] = repo_b_example()[1]
    except pytest.skip.Exception:
        pass
    assert len(inputs) >= 3
    for name in SKETCH_VARIANTS:
        path = _bank_path(name)
        _header, songs = nc.load_bank(path)
        for label, abc in inputs.items():
            # reference side: the library functions, driven independently of check()
            text = Path(abc).read_text(encoding='utf-8')
            parsed = nc.parse_for_tokens(text)
            notes = nc.notes_from_parsed(parsed, None)
            grams, _ids = nc.composition_grams(nc.tokens_from_notes(notes))
            prep = nc.prepare(grams)
            ref = nc.best_match(prep, songs, tiebreak=nc.beats_tiebreak(notes, prep))
            got = parse_line(nc.check(abc, path))
            if ref is None:
                assert got['closest'] == 'none', (name, label, got)
                continue
            containment, _matched, sid = ref
            assert got['closest'] == sid, (name, label, got, sid)
            assert '%.3f' % got['containment'] == '%.3f' % containment, (name, label, got, containment)


def test_match_song_accepts_raw_pairs_and_prepared_alike():
    """The original bug: raw (hash, position) pairs reached the estimator unprepared."""
    nc = load_nc()
    pairs = [(5, 0), (9, 1), (20, 2), (30, 3), (5, 4), (700, 5)]
    prep = nc.prepare(pairs)
    for hs, tau in (({5, 9, 99}, None), ({5, 9, 20}, 25)):
        assert nc.match_song(pairs, hs, tau) == nc.match_song(prep, hs, tau)
    # full bank: distinct hashes {5, 9, 20, 30, 700}; matched {5, 9}
    matched, den = nc.match_song(pairs, {5, 9, 99}, None)
    assert (sorted(matched), den) == ([5, 9], 5)
    # sketch tau=25: comparable distinct hashes {5, 9, 20}; matched {5, 9, 20}
    matched, den = nc.match_song(pairs, {5, 9, 20}, 25)
    assert (sorted(matched), den) == ([5, 9, 20], 3)
    # positions come back for matched_beats
    assert sorted(nc.matched_positions(prep, [5, 9])) == [0, 1, 4]
    with pytest.raises(TypeError):
        nc.match_song([1, 2, 3], {1}, None)           # neither prepared nor pairs


@pytest.mark.parametrize('name', _variant_ids())
def test_header_threshold_is_used_when_no_override_is_given(name, tmp_path):
    nc, _backend = load_checker()
    path = _bank_path(name)
    header, _songs = nc.load_bank(path)
    expected = EXPECTED_THRESHOLDS[name]
    assert nc.default_threshold(header) == pytest.approx(expected), name
    # The splice scores ~0.1 on every bank: above 0.08, below 0.15.  So the status
    # tells which threshold check() really applied.
    splice = control_inputs(tmp_path)['splice']
    r = parse_line(nc.check(splice, path))
    assert 0.08 <= r['containment'] < 0.15, (name, r)
    assert r['status'] == ('close' if expected <= 0.08 else 'ok'), (name, expected, r)
    # an explicit override still wins
    assert parse_line(nc.check(splice, path, threshold=0.05))['status'] == 'close'
    assert parse_line(nc.check(splice, path, threshold=0.5))['status'] == 'ok'


def test_cli_uses_the_same_path_as_check(tmp_path, capsys):
    """main() (the CLI) prints exactly what check() returns, header threshold included."""
    nc, backend = load_checker()
    if backend != 'repo_b':
        pytest.skip('the CLI needs Repo B (abc_common.py) beside the script')
    songs = control_inputs(tmp_path)
    for name in ('corpus_fingerprints.bin', 'corpus_fingerprints.k128.bin'):
        bank = _bank_path(name)
        for label in ('whole', 'splice'):
            capsys.readouterr()
            assert nc.main([str(songs[label]), '--bank', str(bank)]) == 0
            assert capsys.readouterr().out.strip() == nc.check(songs[label], bank), (name, label)


def test_script_runs_as_deployed_beside_abc_common(tmp_path):
    """Copy the script next to Repo B's abc_common.py and run it as the skill will."""
    rb, example = repo_b_example()
    deploy = tmp_path / 'scripts'
    deploy.mkdir()
    shutil.copy(HANDOFF, deploy / 'novelty_check.py')
    shutil.copy(rb / 'scripts' / 'abc_common.py', deploy / 'abc_common.py')
    song = write_abc(tmp_path, 'song.abc', corpus_text(CONTROL_SONG))

    def run(path, *extra):
        out = subprocess.run([sys.executable, str(deploy / 'novelty_check.py'), str(path),
                              '--assets', str(ASSETS), *extra],
                             capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stderr
        return out.stdout.strip()

    assert 'closest=%s' % CONTROL_SONG in run(song) and 'status=close' in run(song)
    assert 'status=ok' in run(example)
    assert 'status=close' in run(song, '--bank', str(ASSETS / 'alt' / 'corpus_fingerprints.full.bin'))
