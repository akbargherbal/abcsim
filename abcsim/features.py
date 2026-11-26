"""features.py -- note list -> transposition- and tempo-invariant tokens."""
import numpy as np
from parse import parse_abc, lead_voice


def tokens_from_notes(notes):
    """token k describes notes k,k+1,k+2:
       interval = pitch(k+1)-pitch(k)   (semitones, clipped to +-12)  -> transposition invariant
       rc       = round(2*log2(IOI(k+1)/IOI(k))) clipped to +-4         -> tempo invariant (x2 / x1/2 safe)"""
    t = np.array([n.onset for n in notes], dtype=np.float64)
    p = np.array([n.midi for n in notes], dtype=np.int32)
    if len(notes) < 4:
        return None
    ioi = np.diff(t)
    ioi = np.where(ioi <= 1e-6, 1e-6, ioi)
    iv = np.clip(np.diff(p)[:-1], -12, 12).astype(np.int8)
    rc = np.clip(np.rint(2 * np.log2(ioi[1:] / ioi[:-1])), -4, 4).astype(np.int8)
    return iv, rc


def song_stream(abc_text, voice=None):
    s = parse_abc(abc_text)
    v = voice or lead_voice(s)
    if v is None or v not in s.voices:
        return None
    notes = s.voices[v]
    tk = tokens_from_notes(notes)
    if tk is None:
        return None
    return dict(song=s, voice=v, notes=notes, iv=tk[0], rc=tk[1])


def token_id(iv, rc):
    return (iv.astype(np.int32) + 12) * 9 + (rc.astype(np.int32) + 4)
