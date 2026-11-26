"""build_index.py -- parse everything once, cache tokens (pickle).

    python abcsim/build_index.py ROOT [--voice lead|vocal|ins] [--cache PATH]

`--voice lead` (default) keeps the old behaviour and cache path.  `vocal` and
`ins` build separate caches so a later all-pairs run can compare like with like.
Songs without the requested voice are skipped and counted.
"""
import argparse
import os
import pickle
import sys

sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
from corpus import load_all
from features import song_stream
from align import token_weights

VOICES = {'lead': None, 'vocal': 'Vocal', 'ins': 'Ins'}


def default_cache(outd, voice):
    return os.path.join(outd, 'index.pkl' if voice == 'lead' else 'index_%s.pkl' % voice)


def build(root, cache='out/index.pkl', voice='lead'):
    if os.path.exists(cache):
        return pickle.load(open(cache, 'rb'))
    voice_name = VOICES.get(voice, voice)
    meta, IV, RC, ON, BR = [], [], [], [], []
    skipped = 0
    for s in load_all(root):
        st = song_stream(s['abc'], voice=voice_name)
        if st is None:
            skipped += 1
            continue
        notes = st['notes']
        # token k is anchored on notes k..k+2: store onset/bar of note k and k+2
        on = np.array([n.onset for n in notes], np.float32)
        br = np.array([n.bar for n in notes], np.int32)
        sg = st['song']
        meta.append(dict(id=s['id'], corpus=s['corpus'], artist=s['artist'], title=s['title'], dup=s.get('dup'),
                         voice=st['voice'], tempo=sg.tempo, key=sg.key, n_notes=len(notes), n_tok=len(st['iv'])))
        IV.append(st['iv']); RC.append(st['rc']); ON.append(on); BR.append(br)
    if not IV:
        raise SystemExit('no usable songs for voice=%r under %s' % (voice, root))
    offs = np.zeros(len(IV) + 1, np.int64); offs[1:] = np.cumsum([len(x) for x in IV])
    ivs = np.concatenate(IV); rcs = np.concatenate(RC)
    W = token_weights(ivs, rcs)
    ws = W[(ivs.astype(np.int32) + 12) * 9 + (rcs.astype(np.int32) + 4)].astype(np.float32)
    idx = dict(meta=meta, ivs=ivs, rcs=rcs, ws=ws, offs=offs, onsets=ON, bars=BR, W=W,
               voice_mode=voice, n_skipped=skipped)
    os.makedirs(os.path.dirname(cache) or '.', exist_ok=True)
    pickle.dump(idx, open(cache, 'wb'))
    return idx


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('root', help='folder containing the .abc files')
    ap.add_argument('--voice', choices=['lead', 'vocal', 'ins'], default='lead')
    ap.add_argument('--cache', help='cache path (default: out/index[_voice].pkl)')
    args = ap.parse_args(argv)
    cache = args.cache or default_cache('out', args.voice)
    idx = build(args.root, cache, args.voice)
    print('%d songs, %d tokens, max len %d, voice=%s, skipped %d' % (
        len(idx['meta']), len(idx['ivs']), np.diff(idx['offs']).max(),
        args.voice, idx.get('n_skipped', 0)))
    print('cache:', cache)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
