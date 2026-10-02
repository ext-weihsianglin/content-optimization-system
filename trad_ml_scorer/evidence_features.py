"""V5 lexical answer/evidence cues on the frozen retention scoring view."""
from collections import defaultdict
import math
import re
import numpy as np
from scripts.analyze_content import STOPWORDS, words
from trad_ml_scorer.robust_features import scoring_view

VERSION = 'lr-evidence-v5'
DESCRIPTIONS = {}
FAMILIES = {}
NUMBER = re.compile(r'\b\d+(?:[.,]\d+)?\b')
UNIT = re.compile(r'(?:\d\s*(?:%|\$|€|£|kg\b|km\b|cm\b|mm\b|hours?\b|minutes?\b|seconds?\b|days?\b|years?\b|mb\b|gb\b|hz\b|watts?\b))|(?:[$€£]\s*\d)',re.I)
DEFINITION = re.compile(r'\b(?:is|are|means|refers to|defined as|because|therefore)\b',re.I)


def coverage(query, tokens):
    return len(query & set(tokens))/max(1,len(query))


def evidence_features(prompt, doc):
    view = scoring_view(doc)
    query = set(words(prompt))-STOPWORDS
    result = {}
    def add(name,value,family,description):
        result[name] = float(value)
        DESCRIPTIONS[name] = description
        FAMILIES.setdefault(family,[])
        if name not in FAMILIES[family]:
            FAMILIES[family].append(name)

    # Only prose-bearing blocks: headings, tables and code are evaluated separately.
    unique = {}
    for b in view['blocks']:
        if b['type'] not in ('paragraph','list_item','blockquote'):
            continue
        for text in re.split(r'(?<=[.!?。！？])\s+|\n+',b.get('text','')):
            tokens = words(text)
            key = tuple(tokens)
            if 6 <= len(tokens) <= 80:
                unique.setdefault(key,{'tokens':tokens,'text':text,'linked':False})
                unique[key]['linked'] |= bool(b.get('links'))
    sentences = list(unique.values())
    scores = [coverage(query,s['tokens']) for s in sentences]
    relevant = [s for s,score in zip(sentences,scores) if score>=.5 and query]
    add('answer_best_sentence_coverage',max(scores,default=0),'answer','How much of the question appears together in one 6–80-word sentence?')
    add('answer_top3_sentence_coverage',np.mean(sorted(scores,reverse=True)[:3]) if scores else 0,'answer','How much question coverage do the three best distinct sentences provide?')
    add('answer_relevant_sentence_fraction',len(relevant)/max(1,len(sentences)),'answer','What fraction of distinct sentences cover at least half the meaningful question words?')
    add('answer_log_relevant_sentences',math.log1p(len(relevant)),'answer','How many distinct question-relevant sentences are available? Large counts are squeezed.')
    add('answer_best_sentence_precision',max((len(query & set(s['tokens']))/len(set(s['tokens'])) for s in sentences),default=0),'answer','How focused is the most question-dense sentence?')
    add('answer_relevant_median_words',math.log1p(np.median([len(s['tokens']) for s in relevant])) if relevant else 0,'answer','How long is a typical relevant sentence?')
    # Sliding windows within prose sentences never cross unrelated blocks.
    for width in (10,25,50):
        best = 0.
        for sentence in sentences:
            tokens = sentence['tokens']
            for i in range(max(1,len(tokens)-width+1)):
                best = max(best,coverage(query,tokens[i:i+width]))
        add(f'answer_window_{width}_coverage',best,'answer',f'How much of the question occurs within a {width}-word prose window?')
    union = set().union(*(set(s['tokens']) for s in relevant)) if relevant else set()
    add('answer_relevant_union_coverage',coverage(query,union),'answer','Together, how much of the question do relevant distinct sentences cover?')
    for name,pattern in [('number',NUMBER),('unit',UNIT),('definition',DEFINITION)]:
        marked = [s for s in relevant if pattern.search(s['text'])]
        add(f'evidence_{name}_fraction',len(marked)/max(1,len(relevant)),'evidence',f'What fraction of relevant sentences contain a {name} cue? This does not verify truth.')
        add(f'evidence_{name}_coverage',max((coverage(query,s['tokens']) for s in marked),default=0),'evidence',f'How well does the best relevant sentence with a {name} cue cover the question?')
    add('evidence_linked_fraction',sum(s['linked'] for s in relevant)/max(1,len(relevant)),'evidence','How often are relevant sentences inside a block with a link? A link need not be a trustworthy citation.')
    numeric_intent = bool(re.search(r'\b(?:how much|how many|cost|price|percent|size|weight|speed|duration)\b',prompt,re.I))
    add('evidence_numeric_intent_alignment',numeric_intent*result['evidence_number_coverage'],'evidence','For a numeric question, does a relevant sentence contain a number?')
    definition_intent = bool(re.search(r'\b(?:what is|what are|define|meaning|why)\b',prompt,re.I))
    add('evidence_definition_intent_alignment',definition_intent*result['evidence_definition_coverage'],'evidence','For a definition or explanation question, does relevant prose use an explanation cue?')
    table_scores, header_scores, numeric_scores, matched_rows = [],[],[],[]
    for b in view['blocks']:
        if b['type']!='table' or not b.get('table'):
            continue
        table = b['table']; rows = defaultdict(list)
        headers = []
        for cell in table['cells']:
            if cell['is_header']:
                headers.extend(words(cell['text']))
            else:
                rows[cell['row']].append(cell['text'])
        header_scores.append(coverage(query,headers))
        # Source row grouping preserves values together; no cross-row concatenation.
        dedup = set()
        for texts in rows.values():
            text = ' '.join(texts); tokens = words(text); key=tuple(tokens)
            if not tokens or key in dedup:
                continue
            dedup.add(key)
            score = coverage(query,tokens)
            table_scores.append(score)
            matched_rows.append(score>=.5 and bool(query))
            if NUMBER.search(text):
                numeric_scores.append(score)
    add('table_best_value_row_coverage',max(table_scores,default=0),'structured','How well does one table data row cover the question, excluding header cells?')
    add('table_top3_value_row_coverage',np.mean(sorted(table_scores,reverse=True)[:3]) if table_scores else 0,'structured','How well do the three best distinct table data rows match?')
    add('table_relevant_row_fraction',sum(matched_rows)/max(1,len(matched_rows)),'structured','What fraction of distinct table data rows cover half the question?')
    add('table_numeric_row_coverage',max(numeric_scores,default=0),'structured','How well does a table data row containing numbers match the question?')
    add('table_header_best_coverage',max(header_scores,default=0),'structured','What is the best question match within the headers of one table?')
    add('table_numeric_intent_alignment',numeric_intent*max(numeric_scores,default=0),'structured','For numeric questions, how relevant is the best numeric table row?')
    indexed={b['block_id']:b for b in view['blocks']}
    step_text=defaultdict(list)
    for block in view['blocks']:
        parent=block.get('parent_id')
        visited=set()
        while parent in indexed and parent not in visited:
            visited.add(parent)
            ancestor=indexed[parent]
            if ancestor['type']=='list_item':
                step_text[parent].append(block.get('text',''))
                break
            parent=ancestor.get('parent_id')
    steps=set()
    for b in view['blocks']:
        if b['type']=='list_item' and indexed.get(b.get('parent_id'),{}).get('ordered'):
            tokens=tuple(words(' '.join([b.get('text',''),*step_text[b['block_id']]])))
            if tokens:
                steps.add(tokens)
    step_scores=[coverage(query,tokens) for tokens in steps]
    add('steps_best_coverage',max(step_scores,default=0),'structured','How well does one distinct numbered step match the question?')
    add('steps_relevant_fraction',sum(s>=.5 and bool(query) for s in step_scores)/max(1,len(steps)),'structured','What fraction of distinct numbered steps cover half the question?')
    add('steps_howto_alignment',int(bool(re.search(r'\bhow\s+to\b',prompt,re.I)))*max(step_scores,default=0),'structured','For how-to questions, is there a matching numbered step?')
    return result
