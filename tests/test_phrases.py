"""Phase 5: every phrase must round-trip through Repo B's degree grammar.

Skips if a local abc_score_composer checkout is not available.  The corpus zip
is in this repository, so the source-note check does not need external data.
"""
import json
import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'abcsim'))
BANK = ROOT / 'handoff' / 'skill_0.2.3' / 'assets' / 'phrase_bank.json'
ZIP = ROOT / '670_arabic_songs_abc_scores.zip'
DEGREE_RE = re.compile(r'^[#b]*[1-7][+\-]*$')


def find_repo_b():
    import repo_b
    return repo_b.find_repo_b()


def load_bank():
    if not BANK.exists():
        pytest.skip('phrase_bank.json is missing')
    return json.loads(BANK.read_text(encoding='utf-8'))


def parse_phrase(phrase):
    """Return (note_degrees, total_beats). Rests are counted but not returned."""
    degrees = []
    total = 0.0
    for tok in phrase.split():
        left, right = tok.split(':', 1)
        total += float(right.rstrip('~'))
        if left != 'r':
            degrees.append(left)
    return degrees, round(total, 6)


def test_roundtrip_phrases():
    repo_b = find_repo_b()
    if repo_b is None:
        pytest.skip('abc_score_composer checkout not found')
    sys.path.insert(0, str(repo_b / 'scripts'))
    from abc_common import parse_key, degree_to_midi  # noqa: E402
    from parse import parse_abc  # noqa: E402

    bank = load_bank()
    assert bank['phrases']
    mismatches = 0
    for p in bank['phrases']:
        degrees, total = parse_phrase(p['phrase'])
        assert abs(total - p['beats']) < 1e-6, p['id']
        assert len(degrees) == len(p['source_midi']), p['id']
        key_info = parse_key(p['source_key'])
        for deg, want in zip(degrees, p['source_midi']):
            assert DEGREE_RE.match(deg), (p['id'], deg)
            got, _letter, _norm = degree_to_midi(deg, key_info)
            if int(got) != int(want):
                mismatches += 1
    assert mismatches == 0


def test_source_notes_exist_in_corpus():
    """The stored source_midi sequence must really occur at source_bars."""
    if not ZIP.exists():
        pytest.skip('corpus zip is missing')
    from parse import parse_abc  # noqa: E402
    bank = load_bank()
    missing = 0
    with zipfile.ZipFile(ZIP) as z:
        for p in bank['phrases']:
            name = '670_arabic_songs_abc_scores/' + p['source_id']
            try:
                text = z.read(name).decode('utf-8')
            except KeyError:
                missing += 1
                continue
            notes = parse_abc(text).voices.get('Vocal', [])
            midis = [n.midi for n in notes]
            want = p['source_midi']
            found = False
            for i in range(0, len(midis) - len(want) + 1):
                if midis[i:i + len(want)] != want:
                    continue
                bars = [notes[j].bar + 1 for j in range(i, i + len(want))]
                if bars[0] == p['source_bars'][0] and bars[-1] == p['source_bars'][1]:
                    found = True
                    break
            if not found:
                missing += 1
    assert missing == 0


def test_every_phrase_has_byte_metadata():
    bank = load_bank()
    for p in bank['phrases']:
        assert p['phrase_bytes'] == len(p['phrase'].encode('utf-8')), p['id']
        assert p['fits_seed_budget'] == (p['phrase_bytes'] <= 130), p['id']


def test_bank_respects_the_byte_limit_it_was_built_with():
    bank = load_bank()
    limit = bank['generated_from']['selection']['max_phrase_bytes']
    if limit:
        assert all(p['phrase_bytes'] <= limit for p in bank['phrases'])
        assert all(p['fits_seed_budget'] for p in bank['phrases']) or limit > 130


def test_mode_quota_is_met_or_shortfall_is_explicit():
    bank = load_bank()
    counts = bank['counts']
    assert 'mode_shortfall' in counts
    sel = bank['generated_from']['selection']
    n = sel['min_per_mode']
    for mode in sel['modes']:
        short = counts['mode_shortfall'].get(mode)
        have = counts['by_mode_hint'].get(mode, 0)
        wanted = 2 * n            # n per cadence class
        if short is None:
            assert have >= wanted, (mode, have, wanted)
        else:
            assert short['got'] < short['wanted'], mode
            assert have >= short['got'], mode
            # a shortfall is never padded with other labels: the quota total is wanted - missing
            assert have >= wanted - (short['wanted'] - short['got']), mode


TOKEN_RE = re.compile(r'^(r|[#b]*[1-7][+\-]*):[0-9]*\.?[0-9]+~?$')


def test_phrase_text_is_pure_degree_grammar_with_no_key():
    """Degrees are tonic-relative: the text carries no key or transposition."""
    bank = load_bank()
    for p in bank['phrases']:
        for tok in p['phrase'].split():
            assert TOKEN_RE.match(tok), (p['id'], tok)
