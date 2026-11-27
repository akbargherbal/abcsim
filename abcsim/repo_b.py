"""repo_b.py -- locate a local checkout of Repo B (abc_score_composer).

Search order, first hit wins:
  1. the ABC_SCORE_COMPOSER environment variable
  2. a sibling folder of this repository:   <abcsim>/../abc_score_composer
  3. the home folder:                        ~/abc_score_composer

A checkout counts when scripts/abc_common.py exists.  Nothing is hardcoded to
a machine-specific path, so this works the same on Windows, macOS and Linux.
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_VAR = 'ABC_SCORE_COMPOSER'


def candidates():
    out = []
    env = os.environ.get(ENV_VAR)
    if env:
        out.append(Path(env).expanduser())
    out.append(REPO_ROOT.parent / 'abc_score_composer')
    out.append(Path.home() / 'abc_score_composer')
    return out


def find_repo_b():
    """Return the Repo B checkout as a Path, or None."""
    for c in candidates():
        if (c / 'scripts' / 'abc_common.py').exists():
            return c
    return None


def not_found_message():
    return ('Repo B (abc_score_composer) not found. Set %s to its folder or clone it next to '
            'this repository. Searched: %s' % (ENV_VAR, ', '.join(str(c) for c in candidates())))
