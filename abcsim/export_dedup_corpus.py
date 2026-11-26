"""export_dedup_corpus.py -- copy only the kept songs into a separate folder.

Reads <outd>/dedupe_keep.txt (written by cluster_dups.py) and copies those
.abc files from the original corpus into <outd>/corpus_dedup/.  The original
corpus is never modified.  The destination is rebuilt from scratch so it
cannot contain stale files from an earlier run.

Usage:
    python abcsim/export_dedup_corpus.py CORPUS_ROOT OUTD [--dest DIR]
"""
import argparse
import shutil
import sys
from pathlib import Path


def read_keep(path):
    return [line.strip() for line in path.read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.strip().startswith('#')]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('corpus', help='original folder containing the .abc files')
    ap.add_argument('outd', nargs='?', default='out', help='folder with dedupe_keep.txt (default: out)')
    ap.add_argument('--dest', help='destination folder (default: OUTD/corpus_dedup)')
    args = ap.parse_args(argv)

    root = Path(args.corpus)
    outd = Path(args.outd)
    keep_path = outd / 'dedupe_keep.txt'
    if not keep_path.exists():
        print('missing %s -- run abcsim/cluster_dups.py first' % keep_path, file=sys.stderr)
        return 2
    ids = read_keep(keep_path)
    dest = Path(args.dest) if args.dest else outd / 'corpus_dedup'

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    missing = []
    for sid in ids:
        src = root / sid
        if not src.is_file():
            missing.append(sid)
            continue
        dst = dest / sid
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    copied = [p for p in dest.rglob('*.abc') if p.is_file()]
    print('kept list: %d files' % len(ids))
    print('copied:    %d files -> %s' % (len(copied), dest))
    if missing:
        print('MISSING %d files (not found under %s):' % (len(missing), root), file=sys.stderr)
        for sid in missing[:20]:
            print('  ' + sid, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
