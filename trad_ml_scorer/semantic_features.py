"""Original-space embedding similarity contract; no PCA or corpus fitting."""
import numpy as np

FIELDS = ['title_similarity', 'h1_similarity', 'outline_similarity', 'page_similarity', 'path_similarity']
SECTIONS = ['section_max', 'section_top3_mean', 'section_median', 'section_q25', 'section_q75']
NAMES = FIELDS + SECTIONS
DESCRIPTIONS = {
    'title_similarity': 'How closely the question and page title match in embedding space.',
    'h1_similarity': 'The closest matching main heading (H1); maximum when there are several.',
    'outline_similarity': 'How closely the question matches the heading outline.',
    'page_similarity': 'How closely the question matches the whole-page representation; long pages use pooled chunks.',
    'path_similarity': 'How closely the question matches the normalized URL path.',
    'section_max': 'The closest matching section chunk anywhere in the page.',
    'section_top3_mean': 'Average match of the three closest section chunks (or all if fewer).',
    'section_median': 'The middle section-chunk match: how relevant a typical chunk is.',
    'section_q25': 'The lower-quarter section-chunk match.',
    'section_q75': 'The upper-quarter section-chunk match.',
}


def original_cosines(query, documents):
    query = np.asarray(query, dtype=np.float32)
    documents = np.asarray(documents, dtype=np.float32)
    if query.ndim != 1 or documents.ndim != 2 or documents.shape[1] != len(query):
        raise ValueError('Query and document vectors must share the original embedding space')
    norms = np.linalg.norm(documents, axis=1)
    qnorm = np.linalg.norm(query)
    if not np.isfinite(query).all() or not np.isfinite(documents).all() or qnorm == 0 or (norms == 0).any():
        raise ValueError('Invalid embedding')
    return (documents / norms[:, None]) @ (query / qnorm)


def section_summary(scores):
    scores = np.asarray(scores)
    if not len(scores):
        return dict.fromkeys(SECTIONS, np.nan)
    if not np.isfinite(scores).all():
        raise ValueError('Nonfinite section similarities')
    return dict(zip(SECTIONS, map(float, [max(scores), np.mean(np.sort(scores)[-3:]), np.median(scores), np.quantile(scores, .25), np.quantile(scores, .75)])))


def validate_join(record, association):
    for name in ('source_file_hash', 'source_row', 'snapshot_id', 'prompt', 'href', 'hostname', 'split'):
        if record[name] != association[name]:
            raise ValueError(f'Association mismatch: {name}')
    if record['html_sha256'] != association['payload_hash']:
        raise ValueError('Association mismatch: payload_hash')
    if record['is_cited_high'] != {'top': 1, 'bottom': 0}[association['citation_category']]:
        raise ValueError('Association mismatch: label')
