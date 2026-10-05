"""Checksum, atomic reports and paired arena acceptance."""
import hashlib
import json
from pathlib import Path

def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def passes(result):
    return (result['complete_pairs'] >= 32 and result['truncated'] == 0
            and result['paired_mean'] >= .52 and result['paired_ci95'][0] > .5)


