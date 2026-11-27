"""Asset budgets and basic schema checks."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'handoff' / 'skill_0.2.3' / 'assets'
PHRASES = ASSETS / 'phrase_bank.json'
DEFAULT_FP = ASSETS / 'corpus_fingerprints.bin'

# Documented sizes (docs/fingerprint_options.md), rounded up with a little slack.
FP_MAX_BYTES = {
    'corpus_fingerprints.bin': 700 * 1000,          # default = recommended bottom-256
    'alt/corpus_fingerprints.full.bin': 1100 * 1000,
    'alt/corpus_fingerprints.k128.bin': 360 * 1000,
    'alt/corpus_fingerprints.k64.bin': 210 * 1000,
}
DEFAULT_MAX_BYTES = int(1.1 * 1024 * 1024)


def test_phrase_bank_size():
    if not PHRASES.exists():
        pytest.skip('phrase_bank.json is missing')
    assert PHRASES.stat().st_size <= 60 * 1024


def test_default_fingerprint_size():
    if not DEFAULT_FP.exists():
        pytest.skip('corpus_fingerprints.bin is missing')
    assert DEFAULT_FP.stat().st_size <= DEFAULT_MAX_BYTES


@pytest.mark.parametrize('rel,limit', sorted(FP_MAX_BYTES.items()))
def test_each_fingerprint_variant_within_documented_size(rel, limit):
    f = ASSETS / rel
    if not f.exists():
        pytest.skip('%s is missing' % rel)
    assert f.stat().st_size <= limit, (rel, f.stat().st_size)


def test_phrase_bank_schema():
    if not PHRASES.exists():
        pytest.skip('phrase_bank.json is missing')
    d = json.loads(PHRASES.read_text(encoding='utf-8'))
    assert d['schema'] == 'phrase_bank/2'
    assert 'phrase_bytes' in d['grammar']['fields_added_in_schema_2']
    assert d['phrases']
    required = {'id', 'beats', 'phrase', 'end_degree', 'cadence_class', 'role_hint',
                'mode_hint', 'source_id', 'source_bars', 'register', 'source_key',
                'source_midi', 'cluster', 'phrase_bytes', 'fits_seed_budget'}
    for p in d['phrases']:
        assert required <= set(p)
        assert p['beats'] in (8, 16)
        assert p['cadence_class'] in ('sadr', 'ajuz')
        assert p['register'] in ('low', 'mid', 'high')
        assert ' ' not in p['end_degree']
        assert p['phrase']
    for cls in ('sadr', 'ajuz'):
        n = d['counts']['by_cadence_class'].get(cls, 0)
        assert 20 <= n <= 28
