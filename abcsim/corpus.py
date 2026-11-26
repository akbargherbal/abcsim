"""corpus.py -- gather every ABC score of the November_2026 bundle into one list."""
import json, glob, os


def load_folder(root):
    """Generic mode: every *.abc under root (recursively). id = relative path, corpus = first sub-folder name."""
    out = []
    for f in sorted(glob.glob(os.path.join(root, '**', '*.abc'), recursive=True)):
        rel = os.path.relpath(f, root)
        parts = rel.split(os.sep)
        out.append(dict(id=rel, corpus=parts[0] if len(parts) > 1 else 'LOCAL', artist=parts[0] if len(parts) > 1 else '',
                        album='', title=os.path.splitext(parts[-1])[0], abc=open(f, encoding='utf-8').read(), dup=None))
    return out


def load_all(root):
    bundle = (glob.glob(os.path.join(root, 'TRANSCRIPTS', 'FADL_SHAKER', 'abc', '*.json')) or
              glob.glob(os.path.join(root, 'TRANSCRIPTS', 'YT500', 'YT500', 'abc', '*.json')))
    if not bundle:
        return load_folder(root)          # your own folder of .abc files (a stray TRANSCRIPTS dir is fine)
    out = []
    for f in sorted(glob.glob(os.path.join(root, 'TRANSCRIPTS/FADL_SHAKER/abc/*.json'))):
        d = json.load(open(f, encoding='utf-8'))
        for t in d['tracks']:
            if t.get('abc'):
                out.append(dict(id=t['track_id'], corpus='FADL', artist='Fadl Shaker', album=d['album'],
                                title=t.get('title'), abc=t['abc'], dup=None))
    dup = {}
    mf = os.path.join(root, 'TRANSCRIPTS/YT500/_manifest.jsonl')
    if os.path.exists(mf):
        for line in open(mf, encoding='utf-8'):
            r = json.loads(line)
            if r.get('record') == 'track':
                dup[r['track_id']] = r.get('duplicate_group')
    for f in sorted(glob.glob(os.path.join(root, 'TRANSCRIPTS/YT500/YT500/abc/*.json'))):
        d = json.load(open(f, encoding='utf-8'))
        for t in d['tracks']:
            if t.get('abc'):
                out.append(dict(id=t['track_id'], corpus='YT500', artist=t.get('artist'), album=d['album'],
                                title=t.get('title'), abc=t['abc'], dup=dup.get(t['track_id'])))
    for f in sorted(glob.glob(os.path.join(root, 'TRANSCRIPTS/fadhl_shaker_selected_scores/*/score.abc'))):
        n = f.split('/')[-2]
        out.append(dict(id='SEL/' + n, corpus='SEL', artist='Fadl Shaker', album='selected', title=n,
                        abc=open(f, encoding='utf-8').read(), dup=None))
    for f in sorted(glob.glob(os.path.join(root, 'DATASET/fadhl_shaker_instrumental_18/abc/*.abc'))):
        n = os.path.basename(f)[:-4]
        out.append(dict(id='GEN/' + n, corpus='GEN', artist='Fadl Shaker (generated-instrumental conditioner)',
                        album='instrumental_18', title=n, abc=open(f, encoding='utf-8').read(), dup=None))
    return out
