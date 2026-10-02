"""Materialize the pinned official Voyage nano checkpoint, never remote Python code."""
import argparse
from pathlib import Path
from huggingface_hub import snapshot_download

from representations.cache import default_cache_root
from representations.config import load_config
from representations.storage import digest, file_hash, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output')
    parser.add_argument('--config')
    args = parser.parse_args()
    cfg = load_config(args.config)['models']['voyage-nano']
    root = Path(args.output or default_cache_root('.').parent.parent / 'models' / 'voyage-4-nano')
    snapshot_download(cfg['model'], revision=cfg['revision'], local_dir=root,
                      allow_patterns=cfg['checkpoint_files'] + ['LICENSE.txt', 'NOTICE.txt'], max_workers=2)
    hashes = {name:file_hash(root / name) for name in cfg['checkpoint_files']}
    if digest(hashes) != cfg['checkpoint_hash']:
        raise ValueError('Downloaded checkpoint checksum differs from pinned configuration')
    write_json(root/'source.json', {'model':cfg['model'],'revision':cfg['revision'],'path':str(root.resolve())})
    write_json(root/'checkpoint-manifest.json', {'revision':cfg['revision'],'files':hashes,'checkpoint_hash':digest(hashes)})
    print(root.resolve())


if __name__ == '__main__':
    main()
