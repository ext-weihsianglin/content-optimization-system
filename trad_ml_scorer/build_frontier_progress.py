"""Render development search and guardrail evidence; no test results implied."""
import html
import json
import argparse
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=("v3", "v4"), default="v3")
    version = parser.parse_args().version
    root = Path('trad_ml_scorer') / version
    search, audit, stress = [json.loads((root/f'{name}.json').read_text()) for name in ('search','audit','stress')]
    finalists = search['finalists']
    fig, ax = plt.subplots(figsize=(9,4))
    x = np.arange(len(finalists))
    ax.bar(x-.18,[r['cv_auc'] for r in finalists],.36,label='Training host-grouped CV')
    ax.bar(x+.18,[r['validation']['roc_auc'] for r in finalists],.36,label='Validation')
    ax.set(xticks=x,xticklabels=[r['variant'] for r in finalists],ylabel='ROC-AUC',ylim=(.60,.70),title='Development frontier — test not accessed')
    ax.legend();fig.tight_layout();fig.savefig(root/'development-frontier.svg');plt.close(fig)
    fig, axes = plt.subplots(1,2,figsize=(13,7))
    for ax,variant in zip(axes,('lexical','all')):
        item = next(r for r in audit['audits'] if r['variant']==variant)
        rows = sorted(item['permutation'],key=lambda r:r['auc_drop'])[-15:]
        ax.barh([r['feature'] for r in rows],[r['auc_drop'] for r in rows],xerr=[r['std'] for r in rows])
        ax.set(title=variant,xlabel='Validation ROC-AUC drop (20 permutations)')
    fig.tight_layout();fig.savefig(root/'permutation-frontier.svg');plt.close(fig)
    fig, ax = plt.subplots(figsize=(9,4))
    values = stress['variants']
    ax.bar(list(values),[v['query_headings']['mean_delta'] for v in values.values()],label='Mean score increase')
    ax.scatter(list(values),[v['query_headings']['p95_increase'] for v in values.values()],color='red',label='95th percentile increase')
    ax.set(ylabel='Change in predicted probability',title='Adding 20 identical query headings — 120 validation documents');ax.legend()
    fig.tight_layout();fig.savefig(root/'heading-stress.svg');plt.close(fig)
    body = '''<h1>LR development frontier — in progress</h1><p>Training CV and validation improve with richer features. No candidate is promoted and test has not been accessed. Duplicate-heading manipulation remains unresolved; balanced importance alone is insufficient.</p>'''
    for name in ('development-frontier','permutation-frontier','heading-stress'):
        body += (root/f'{name}.svg').read_text().split('?>',1)[-1]
    body += '<h2>ELI5: added features</h2><dl>'
    for name,description in search['manifest']['descriptions'].items():
        body += f'<dt>{html.escape(name)}</dt><dd>{html.escape(description)}</dd>'
    body += '</dl><h2>Next round</h2><p>Test unique-heading and deduplicated-section features, diminishing returns for repeated structure, and training-only augmentation against query stuffing. Keep hostname assignments and frozen v1/v2 intact. Choose using development AUC and guardrails before one reused-test evaluation. New hosts remain necessary for independent confirmation.</p>'
    (root/'progress.html').write_text('<!doctype html><html><head><meta charset="utf-8"><title>LR development frontier</title><style>body{font:16px system-ui;max-width:1200px;margin:40px auto;padding:20px}svg{max-width:100%;height:auto}dt{font-weight:bold;margin-top:12px}dd{margin:4px 0 16px}</style></head><body>'+body+'</body></html>')

    for path in root.iterdir():
        if path.suffix in ('.svg', '.html'):
            path.write_text('\n'.join(line.rstrip() for line in path.read_text().splitlines()) + '\n')

if __name__ == '__main__':
    main()
