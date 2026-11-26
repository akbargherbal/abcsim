"""Phase 6: novelty_check example + self-containment and runtime."""
import importlib.util
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / 'handoff' / 'skill_0.2.3' / 'scripts' / 'novelty_check.py'
BANK = ROOT / 'handoff' / 'skill_0.2.3' / 'assets' / 'corpus_fingerprints.bin'
CORPUS = Path('/tmp/opencode/corpus670/670_arabic_songs_abc_scores')


def find_repo_b():
    for c in [Path('/tmp/opencode/abc_score_composer'),
              ROOT.parent / 'abc_score_composer',
              Path.home() / 'abc_score_composer']:
        if (c / 'scripts' / 'abc_common.py').exists():
            return c
    return None


def load_novelty():
    repo_b = find_repo_b()
    if repo_b is None:
        pytest.skip('abc_score_composer checkout not found')
    if not HANDOFF.exists() or not BANK.exists():
        pytest.skip('handoff novelty assets are missing')
    sys.path.insert(0, str(repo_b / 'scripts'))
    spec = importlib.util.spec_from_file_location('novelty_check_test', HANDOFF)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, repo_b


def test_example_song_stays_below_threshold():
    novelty, repo_b = load_novelty()
    example = repo_b / 'assets' / 'example_song.abc'
    if not example.exists():
        pytest.skip('example_song.abc is missing')
    t0 = time.perf_counter()
    line = novelty.check(example, BANK, threshold=0.05)
    dt = time.perf_counter() - t0
    assert 'status=ok' in line
    assert dt < 1.0
    # extract containment
    cont = float(line.split('containment=')[1].split()[0])
    assert cont < 0.05


def test_self_containment_on_kept_song():
    novelty, _repo_b = load_novelty()
    if not CORPUS.exists():
        pytest.skip('extracted corpus is missing')
    keep = (ROOT / 'out' / 'dedupe_keep.txt').read_text(encoding='utf-8').split()
    if not keep:
        pytest.skip('dedupe_keep.txt is empty')
    header, _songs = novelty.load_bank(BANK)
    bank_ids = {s['id'] for s in header['songs']}
    sid = next((k for k in keep if k in bank_ids), None)
    if sid is None:
        pytest.skip('no kept song has a fingerprint')
    line = novelty.check(CORPUS / sid, BANK, threshold=0.05)
    cont = float(line.split('containment=')[1].split()[0])
    assert cont > 0.9
