"""V6 independent metadata corroboration, long prose, and lexical normalization."""
from collections import Counter
import math
import re
from urllib.parse import unquote, urlsplit
import numpy as np
from scripts.analyze_content import STOPWORDS, words
from trad_ml_scorer.robust_features import scoring_view, robust_features
from trad_ml_scorer.evidence_features import evidence_features, coverage

VERSION='lr-controls-v6'
METADATA_MATCHES=['coverage_title']+[f'{region}_query_{metric}' for region in ('title','path') for metric in ('precision','dice','saturated_tf','bigram')]
DESCRIPTIONS={}
FAMILIES={}
ALIASES={'kilogram':'kg','kilograms':'kg','gram':'g','grams':'g','meter':'m','meters':'m','metre':'m','metres':'m',
         'centimeter':'cm','centimeters':'cm','centimetre':'cm','centimetres':'cm','kilometer':'km','kilometers':'km',
         'hour':'h','hours':'h','minute':'min','minutes':'min','second':'sec','seconds':'sec',
         'percent':'percent','percentage':'percent','dollar':'usd','dollars':'usd','kilometre':'km','kilometres':'km'}
PLURAL_EXCEPTIONS={'news','series','species','analysis','basis','crisis','status','physics','economics','mathematics'}
NORMAL_TOKEN=re.compile(r'\d+(?:\.\d+)?|[^\W\d_]+',re.UNICODE)


def normalized_tokens(text):
    text=text.casefold()
    text=re.sub(r'(?<=\d),(?=\d{3}(?:\D|$))','',text)
    text=text.replace('%',' percent ').replace('$',' usd ').replace('€',' eur ').replace('£',' gbp ')
    for original,canonical in (('e-mail','email'),('web-site','website'),('on-line','online')):
        text=text.replace(original,canonical)
    result=[]
    for token in NORMAL_TOKEN.findall(text):
        if re.fullmatch(r'\d+(?:\.\d+)?',token):
            if '.' in token:
                token=token.rstrip('0').rstrip('.')
            whole,sep,fraction=token.partition('.')
            token=(whole.lstrip('0') or '0')+(sep+fraction if sep else '')
        elif token in ALIASES:
            token=ALIASES[token]
        elif token not in PLURAL_EXCEPTIONS:
            if len(token)>4 and token.endswith('ies'):
                token=token[:-3]+'y'
            elif len(token)>4 and token.endswith(('ches','shes','xes','zes','sses')):
                token=token[:-2]
            elif len(token)>3 and token.endswith('s') and not token.endswith(('ss','us','is','ics')):
                token=token[:-1]
        result.append(ALIASES.get(token,token))
    return result


def window_coverage(query,tokens,width):
    if not tokens or not query:
        return 0.
    counts=Counter(tokens[:width]); hits=sum(counts[t]>0 for t in query); best=hits
    for i in range(width,len(tokens)):
        old,new=tokens[i-width],tokens[i]
        counts[old]-=1
        if old in query and counts[old]==0:
            hits-=1
        if new in query and counts[new]==0:
            hits+=1
        counts[new]+=1
        best=max(best,hits)
    return best/len(query)


def control_features(prompt,doc,base=None):
    if base is None:
        base={**robust_features(prompt,doc),**evidence_features(prompt,doc)}
    view=scoring_view(doc); result={}
    def add(name,value,family,description):
        result[name]=float(value)
        DESCRIPTIONS[name]=description
        FAMILIES.setdefault(family,[])
        if name not in FAMILIES[family]:
            FAMILIES[family].append(name)
    for name in METADATA_MATCHES:
        add('supported_'+name,base[name]*base['answer_best_sentence_coverage'],'corroboration',
            f'{name} multiplied by best answer-sentence coverage: metadata gets lexical credit only when prose also matches.')
    query=set(words(prompt))-STOPWORDS
    long_segments=set(); prose=[]
    for block in view['blocks']:
        if block['type'] not in ('paragraph','list_item','blockquote'):
            continue
        for text in re.split(r'(?<=[.!?。！？])\s+|\n+',block.get('text','')):
            tokens=tuple(words(text))
            if 6<=len(tokens)<=80:
                prose.append(text)
            if len(tokens)>80:
                long_segments.add(tokens)
    for width in (10,25,50):
        scores=[window_coverage(query,t,width) for t in long_segments]
        add(f'long_window_{width}_best',max(scores,default=0),'long_prose',f'Best question coverage inside a {width}-word window in prose segments longer than 80 tokens.')
        add(f'long_window_{width}_mean',np.mean(scores) if scores else 0,'long_prose',f'Average best {width}-word question coverage across distinct long prose segments; exact repetition receives no extra count.')
    normalized_query=set(normalized_tokens(prompt))-STOPWORDS
    path=unquote(urlsplit(doc['source']['href']).path).replace('_',' ')
    regions={'title':doc['source_metadata'].get('title') or '', 'path':path, 'body':view['text']}
    for region,text in regions.items():
        tokens=normalized_tokens(text)
        score=coverage(normalized_query,tokens)
        add(f'normalized_{region}_coverage',score,'normalization',f'Question-word coverage in {region} after fixed plural, spelling, unit and number normalization.')
        literal=coverage(query,words(text))
        add(f'normalized_{region}_gain',score-literal,'normalization',f'Change in {region} coverage from lexical normalization; may be negative when normalization changes token sets.')
    distinct={tuple(normalized_tokens(text)) for text in prose}
    for width in (10,25):
        add(f'normalized_prose_window_{width}',max((window_coverage(normalized_query,t,width) for t in distinct),default=0),'normalization',f'Best {width}-word prose coverage after normalization, using the same 6–80-token sentence eligibility as v5.')
    numeric_query={t for t in normalized_query if re.fullmatch(r'\d+(?:\.\d+)?',t)}
    add('normalized_number_coverage',coverage(numeric_query,normalized_tokens(view['text'])),'normalization','Do the explicit numbers in the question appear in the body after numeric-format normalization? Units are not converted.')
    for name in ('normalized_title_coverage','normalized_title_gain','normalized_path_coverage','normalized_path_gain'):
        add('supported_'+name,result[name]*base['answer_best_sentence_coverage'],'combined_support',f'{name} multiplied by prose support, keeping combined metadata corroboration intact.')
    return result
