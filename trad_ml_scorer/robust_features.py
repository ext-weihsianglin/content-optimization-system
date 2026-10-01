"""V4 scoring view: suppress repeated and unsupported headings, preserve parser output."""
import copy
from scripts.analyze_content import words
from trad_ml_scorer.frontier_features import richer_features
from trad_ml_scorer.retention_features import features_from_document

VERSION = 'lr-frontier-v4'


def scoring_view(doc):
    """A heading must introduce content before the next heading; duplicates count once.

    This affects scoring only. The source-of-truth document is never modified.
    Parent headings immediately followed by subheadings do not contribute heading
    features in this version, an explicit tradeoff tested against the frozen baseline.
    """
    view = copy.deepcopy(doc)
    blocks = doc['blocks']
    kept, seen = [], set()
    for i, block in enumerate(blocks):
        if block['type'] == 'heading':
            key = ' '.join(words(block.get('text', '')))
            following = []
            for later in blocks[i+1:]:
                if later['type'] == 'heading':
                    break
                following.extend(words(later.get('text', '')))
            if key in seen or not key or len(following) < 5:
                continue
            seen.add(key)
        kept.append(block)
    view['blocks'] = kept
    view['text'] = '\n'.join(b.get('text','') for b in kept if b.get('text'))
    # Heading-only documents keep their text for body matching, but receive no
    # supported-heading credit. This preserves frozen population eligibility.
    if not view['text'].strip():
        view['text'] = doc['text']
    return view


def robust_features(prompt, doc):
    view = scoring_view(doc)
    return {**features_from_document(prompt, view), **richer_features(prompt, view)}
