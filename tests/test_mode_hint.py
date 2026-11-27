"""Hand-written cases for export_phrases.mode_hint (the Phase 2 classifier).

pc_counts maps pitch class relative to the tonic (0..11) -> note count.
Degree names: 0=1, 1=b2, 2=2, 3=b3, 4=3, 5=4, 6=b5, 7=5, 8=b6, 9=6, 10=b7, 11=7.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'abcsim'))
import export_phrases as ep  # noqa: E402


def hint(counts, minor=True):
    return ep.mode_hint(counts, sum(counts.values()), minor)


def test_kurd_phrase_using_4_and_5():
    # 1 4 5 b2 b3 : the old template omitted degrees 4 and 5 and penalised this
    assert hint({0: 2, 5: 1, 7: 2, 1: 1, 3: 1}) == 'kurd-like'


def test_nahawand_with_natural_2_and_b6():
    assert hint({0: 2, 2: 2, 5: 1, 7: 1, 8: 1}) == 'nahawand-like'


def test_nahawand_tolerates_raised_seventh():
    assert hint({0: 2, 2: 2, 3: 1, 5: 1, 7: 1, 11: 1}) == 'nahawand-like'


def test_hijaz_with_b2_and_natural_3():
    assert hint({0: 2, 1: 2, 4: 1, 5: 1, 7: 1, 8: 1}) == 'hijaz-like'


def test_thin_evidence_is_minor_like():
    assert hint({0: 2, 3: 1, 7: 2}) == 'minor-like'          # only 1 b3 5
    assert hint({0: 2, 3: 1, 7: 2}, minor=False) == 'major-like'


def test_no_second_is_ambiguous_not_nahawand():
    # lots of notes, but neither b2 nor 2: must not guess nahawand
    assert hint({0: 3, 3: 2, 5: 2, 7: 2, 8: 1}) == 'minor-like'


def test_too_few_notes():
    assert hint({0: 1, 1: 1, 3: 1, 5: 1, 7: 1}) == 'minor-like'   # 5 notes


def test_p010_is_no_longer_saba():
    # P010 of the 0.2.3 bank: degrees 1 4 b2 b3 b6 b7, no b5
    counts = {5: 7, 3: 4, 1: 7, 0: 10, 10: 4, 8: 3}
    assert hint(counts) != 'saba-like'
    assert hint(counts) == 'kurd-like'


def test_saba_needs_b5_with_b3():
    assert hint({0: 2, 1: 2, 3: 2, 6: 1, 7: 1, 8: 1}) == 'saba-like'


def test_bayati_needs_natural_6():
    assert hint({0: 2, 1: 2, 3: 2, 5: 1, 7: 1, 9: 1}) == 'bayati-like'


def test_rast_and_major():
    assert hint({0: 2, 2: 2, 4: 1, 5: 1, 7: 1, 10: 1}, minor=False) == 'rast-like'
    assert hint({0: 2, 2: 2, 4: 1, 5: 1, 7: 1, 11: 1}, minor=False) == 'major-like'


def test_major_without_seventh_evidence_is_not_rast():
    # 1 2 3 4 5 6 with no b7: rast needs the b7
    assert hint({0: 2, 2: 2, 4: 1, 5: 1, 7: 1, 9: 1}, minor=False) == 'major-like'


def test_mixed_b2_and_2_is_ambiguous():
    assert hint({0: 2, 1: 2, 2: 2, 3: 1, 5: 1}) == 'minor-like'


def test_stray_passing_b2_does_not_flip_a_nahawand_phrase():
    assert hint({0: 2, 1: 1, 2: 3, 3: 2, 5: 1, 7: 1}) == 'nahawand-like'


def test_legacy_classifier_is_still_available_for_audits():
    # documents the old bias: same Kurd-shaped phrase, old label was not kurd
    assert ep.mode_hint_legacy({0: 2, 5: 1, 7: 2, 1: 1, 3: 1}, 7, True) != 'kurd-like'

