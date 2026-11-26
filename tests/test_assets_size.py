"""Phase 7 asset budgets and basic schema checks."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'handoff' / 'skill_0.2.3' / 'assets'
PHRASES = ASSETS / 'phrase_bank.json'
FINGERPRINTS = ASSETS / 'corpus_fingerprints.bin'


def test_phrase_bank_size():
    if not PHRASES.exists():
        pytest.skip('phrase_bank.json is missing')
    assert PHRASES.stat().st_size <= 60 * 1024


def test_fingerprint_size():
    if not FINGERPRINTS.exists():
        pytest.skip('corpus_fingerprints.bin is missing')
    assert FINGERPRINTS.stat().st_size <= 1024 * 1024


def test_phrase_bank_schema():
    if not PHRASES.exists():
        pytest.skip('phrase_bank.json is missing')
    d = json.loads(PHRASES.read_text(encoding='utf-8'))
    assert d['schema'] == 1
    assert d['phrases']
    required = {'id', 'beats', 'phrase', 'end_degree', 'cadence_class', 'role_hint',
                'mode_hint', 'source_id', 'source_bars', 'register', 'source_key',
                'source_midi', 'cluster'}
    for p in d['phrases']:
        assert required <= set(p)
        assert p['beats'] in (8, 16)
        assert p['cadence_class'] in ('sadr', 'ajuz')
        assert p['register'] in ('low', 'mid', 'high')
        assert ' ' not in p['end_degree']
        assert p['phrase']
    for cls in ('sadr', 'ajuz'):
        n = d['counts']['by_cadence_class'].get(cls, 0)
        assert 20 <= n <= 40
