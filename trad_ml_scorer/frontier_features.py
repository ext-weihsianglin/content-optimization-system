"""Deterministic v3 candidates from frozen retention documents; no corpus fitting."""
from collections import Counter
import math
import re
from urllib.parse import unquote, urlsplit

import numpy as np
from scripts.analyze_content import words
from trad_ml_scorer.retention_features import sections_from_blocks

VERSION = 'lr-frontier-v3'
DESCRIPTIONS = {}
FAMILIES = {}


def richer_features(prompt, doc):
    """Only prompt, retained content, and source metadata enter these features."""
    result = {}

    def add(name, value, family, description):
        result[name] = float(value)
        DESCRIPTIONS[name] = description
        FAMILIES.setdefault(family, [])
        if name not in FAMILIES[family]:
            FAMILIES[family].append(name)

    query = words(prompt)
    qset = set(query)
    body = words(doc['text'])
    blocks = doc['blocks']
    sections = [words(' '.join(s['texts'])) for s in sections_from_blocks(blocks)]
    title = words(doc['source_metadata'].get('title') or '')
    description = words(doc['source_metadata'].get('description') or '')
    path = words(unquote(urlsplit(doc['source']['href']).path).replace('-', ' ').replace('_', ' '))
    headings = words(' '.join(b.get('text', '') for b in blocks if b['type'] == 'heading'))
    qbigram = set(zip(query, query[1:]))
    for region, tokens in [('body', body), ('title', title), ('description', description), ('path', path), ('headings', headings)]:
        counts = Counter(tokens)
        overlap = qset & counts.keys()
        denom = max(1, len(qset))
        add(f'{region}_query_precision', len(overlap) / max(1, len(counts)), 'lexical', f'How much of the distinct {region} vocabulary belongs to the question?')
        add(f'{region}_query_dice', 2 * len(overlap) / max(1, len(qset) + len(counts)), 'lexical', f'How similar are the question and {region} word sets, accounting for both lengths?')
        add(f'{region}_query_saturated_tf', sum(counts[t] / (counts[t] + 2) for t in qset) / denom, 'lexical', f'How often do question words appear in {region}, with diminishing credit for repeats?')
        add(f'{region}_query_bigram', len(qbigram & set(zip(tokens, tokens[1:]))) / max(1, len(qbigram)), 'lexical', f'What fraction of adjacent question-word pairs appear together in {region}?')
    scores = [len(qset & set(s)) / max(1, len(qset)) for s in sections]
    best = int(np.argmax(scores)) if scores else 0
    for threshold in (.5, .8, 1.):
        add(f'section_coverage_fraction_{str(threshold).replace(".", "_")}', sum(s >= threshold for s in scores) / max(1, len(scores)), 'relevance', f'What fraction of sections cover at least {threshold:.0%} of question words?')
    add('section_coverage_std', np.std(scores) if scores else 0, 'relevance', 'Is question coverage spread evenly across sections or concentrated in a few?')
    add('top_three_section_coverage', np.mean(sorted(scores, reverse=True)[:3]) if scores else 0, 'relevance', 'How well do the three best sections cover the question?')
    add('best_section_log_words', math.log1p(len(sections[best])) if sections else 0, 'relevance', 'How long is the section that best matches the question?')
    positions = [i for i, token in enumerate(body) if token in qset]
    add('first_query_match_position', positions[0] / max(1, len(body)) if positions else 1, 'relevance', 'How far into the page is the first question word?')
    add('query_match_density', len(positions) / max(1, len(body)), 'relevance', 'What fraction of page words match the question?')
    paragraphs = [words(b.get('text', '')) for b in blocks if b['type'] == 'paragraph']
    lengths = [len(p) for p in paragraphs]
    add('paragraph_log_median_words', math.log1p(np.median(lengths)) if lengths else 0, 'composition', 'How long is a typical paragraph?')
    add('paragraph_log_p90_words', math.log1p(np.quantile(lengths, .9)) if lengths else 0, 'composition', 'How long are the longer paragraphs?')
    add('short_paragraph_fraction', sum(10 <= n <= 60 for n in lengths) / max(1, len(lengths)), 'composition', 'How many paragraphs are short, readable chunks of 10 to 60 words?')
    add('unique_word_fraction', len(set(body)) / max(1, len(body)), 'composition', 'How much vocabulary variety does the page have? This also depends on length.')
    add('numeric_word_fraction', sum(any(c.isdigit() for c in w) for w in body) / max(1, len(body)), 'composition', 'How often does the page include numbers?')
    heading_texts = [b.get('text', '') for b in blocks if b['type'] == 'heading']
    add('question_heading_fraction', sum('?' in h for h in heading_texts) / max(1, len(heading_texts)), 'composition', 'How many headings are written as questions?')
    add('duplicate_heading_fraction', 1 - len(set(h.casefold() for h in heading_texts)) / max(1, len(heading_texts)) if heading_texts else 0, 'composition', 'How often are headings repeated?')
    links = [link for b in blocks for link in b.get('links', [])]
    add('log_link_count', math.log1p(len(links)), 'composition', 'How many links appear in retained blocks?')
    add('links_per_1000_words', 1000 * len(links) / max(1, len(body)), 'composition', 'How link-heavy is the page relative to its length?')
    for kind in ['heading', 'paragraph', 'list_item', 'table', 'code']:
        count = sum(len(words(b.get('text', ''))) for b in blocks if b['type'] == kind)
        add(f'{kind}_word_fraction', min(1, count / max(1, len(body))), 'composition', f'How much retained text is inside {kind.replace("_", " ")} blocks?')
    return result
