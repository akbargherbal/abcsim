"""Phase 6: stdlib tokenizer in novelty_check.py must match features.py on all 670."""
import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ZIP = ROOT / '670_arabic_songs_abc_scores.zip'
HANDOFF = ROOT / 'handoff' / 'skill_0.2.3' / 'scripts' / 'novelty_check.py'


def find_repo_b():
    candidates = [
        Path('/tmp/opencode/abc_score_composer'),
        ROOT.parent / 'abc_score_composer',
        Path.home() / 'abc_score_composer',
    ]
    for c in candidates:
        if (c / 'scripts' / 'abc_common.py').exists():
            return c
    return None


def load_novelty():
    repo_b = find_repo_b()
    if repo_b is None:
        pytest.skip('abc_score_composer checkout not found')
    if not HANDOFF.exists():
        pytest.skip('handoff novelty_check.py is missing')
    sys.path.insert(0, str(repo_b / 'scripts'))
    spec = importlib.util.spec_from_file_location('novelty_check_handoff', HANDOFF)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_token_parity_all_songs():
    novelty = load_novelty()
    sys.path.insert(0, str(ROOT / 'abcsim'))
    from parse import parse_abc, lead_voice
    from features import tokens_from_notes

    if not ZIP.exists():
        pytest.skip('corpus zip is missing')
    mismatches = []
    with zipfile.ZipFile(ZIP) as z:
        names = sorted(n for n in z.namelist() if n.endswith('.abc'))
        assert len(names) == 670
        for name in names:
            text = z.read(name).decode('utf-8')
            song = parse_abc(text)
            lv = lead_voice(song)
            ours = tokens_from_notes(song.voices[lv])
            theirs = novelty.tokens_from_text(text, voice=lv)
            if ours is None or theirs is None:
                if ours is not None or theirs is not None:
                    mismatches.append(name.split('/')[-1])
                continue
            if list(ours[0]) != list(theirs[0]) or list(ours[1]) != list(theirs[1]):
                mismatches.append(name.split('/')[-1])
    assert not mismatches, 'token mismatches: %s' % mismatches[:20]


def test_hash_function_matches_exporter():
    novelty = load_novelty()
    sys.path.insert(0, str(ROOT / 'abcsim'))
    import export_fingerprints
    ids = [0, 1, 2, 17, 255, 256, 1234, 65535]
    assert novelty.hash_ngram(ids) == export_fingerprints.hash_ngram(ids)
