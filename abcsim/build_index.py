"""build_index.py -- parse everything once, cache tokens (pickle)."""
import sys, os, pickle
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
from corpus import load_all
from features import song_stream
from align import token_weights


def build(root, cache='out/index.pkl'):
    if os.path.exists(cache):
        return pickle.load(open(cache, 'rb'))
    meta, IV, RC, ON, BR = [], [], [], [], []
    for s in load_all(root):
        st = song_stream(s['abc'])
        if st is None:
            continue
        notes = st['notes']
        # token k is anchored on notes k..k+2: store onset/bar of note k and k+2
        on = np.array([n.onset for n in notes], np.float32)
        br = np.array([n.bar for n in notes], np.int32)
        sg = st['song']
        meta.append(dict(id=s['id'], corpus=s['corpus'], artist=s['artist'], title=s['title'], dup=s.get('dup'),
                         voice=st['voice'], tempo=sg.tempo, key=sg.key, n_notes=len(notes), n_tok=len(st['iv'])))
        IV.append(st['iv']); RC.append(st['rc']); ON.append(on); BR.append(br)
    offs = np.zeros(len(IV) + 1, np.int64); offs[1:] = np.cumsum([len(x) for x in IV])
    ivs = np.concatenate(IV); rcs = np.concatenate(RC)
    W = token_weights(ivs, rcs)
    ws = W[(ivs.astype(np.int32) + 12) * 9 + (rcs.astype(np.int32) + 4)].astype(np.float32)
    idx = dict(meta=meta, ivs=ivs, rcs=rcs, ws=ws, offs=offs, onsets=ON, bars=BR, W=W)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    pickle.dump(idx, open(cache, 'wb'))
    return idx


if __name__ == '__main__':
    idx = build(sys.argv[1])
    print(len(idx['meta']), 'songs,', len(idx['ivs']), 'tokens, max len', np.diff(idx['offs']).max())
