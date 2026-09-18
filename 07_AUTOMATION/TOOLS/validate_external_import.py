import json
from pathlib import Path

REQUIRED = {'manifest_id', 'source_hash', 'target_niche', 'authority', 'files'}
def validate(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    missing = REQUIRED - data.keys()
    if missing or data.get('authority') == 'CANON_WRITE':
        raise ValueError(f'invalid import manifest: {sorted(missing)}')
    return data
