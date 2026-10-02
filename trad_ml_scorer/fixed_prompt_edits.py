"""Content-preserving HTML edit probes and exact linear-model contrast attribution."""
from collections import Counter
import re
import numpy as np
from bs4 import BeautifulSoup
from scripts.analyze_content import STOPWORDS, words
from trad_ml_scorer.feature_dependencies import GROUPS, feature_group, feature_metadata, fixed_for_html_edit


def transform(model,x):
    return model[1].transform(model[0].transform(x))


def contrast(model,names,before,after):
    before=np.asarray(before).reshape(1,-1);after=np.asarray(after).reshape(1,-1)
    terms=(transform(model,after)-transform(model,before))[0]*model[-1].coef_[0]
    transformed=model[0].get_feature_names_out(names)
    delta=float(model.decision_function(after)[0]-model.decision_function(before)[0])
    np.testing.assert_allclose(terms.sum(),delta,atol=1e-10)
    contributions=[{'feature':str(n),'group':feature_group(str(n)),'html_edit_role':feature_metadata(str(n))['html_edit_role'],'delta_log_odds':float(v)} for n,v in zip(transformed,terms)]
    for row in contributions:
        if fixed_for_html_edit(row['feature']):
            assert abs(row['delta_log_odds'])<1e-12
    return {'before_probability':float(model.predict_proba(before)[0,1]),
            'after_probability':float(model.predict_proba(after)[0,1]),
            'delta_log_odds':delta,'contributions':contributions}


def body_words(soup):
    cloned=BeautifulSoup(str(soup.body or soup),'html.parser')
    for node in cloned.select('head, title, script, style, noscript, template'):
        node.decompose()
    return Counter(words(cloned.get_text(' ',strip=True)))


def make_edit(payload,prompt,action):
    """Return one deterministic edit, or an explicit non-applicability reason.

    No query text or new factual assertion is inserted. These transformations are
    editorial probes needing review, not certified improvements in readability.
    """
    soup=BeautifulSoup(payload,'html.parser')
    body_before=body_words(soup)
    if action=='title_from_existing_h1':
        heading=next((h for h in soup.find_all('h1') if not h.find_parent(['nav','header','footer','aside']) and 2<=len(words(h.get_text(' ',strip=True)))<=20),None)
        if heading is None:return None,'No short content H1'
        title=heading.get_text(' ',strip=True)
        if soup.title and soup.title.get_text(' ',strip=True)==title:return None,'Title already equals H1'
        if soup.title:soup.title.string=title
        else:
            tag=soup.new_tag('title');tag.string=title
            if soup.head:soup.head.append(tag)
            elif soup.html:
                head=soup.new_tag('head');head.append(tag);soup.html.insert(0,head)
            else:soup.insert(0,tag)
        detail='Use an existing content H1 as the title; body wording unchanged.'
    elif action=='relevant_paragraph_first':
        query=set(words(prompt))-STOPWORDS
        if not query:return None,'No meaningful query tokens'
        chosen=None
        for container in soup.find_all(['main','article','section','div','body']):
            if container.find_parent(['nav','header','footer','aside']):continue
            paragraphs=[p for p in container.find_all('p',recursive=False) if len(words(p.get_text(' ',strip=True)))>=15]
            if len(paragraphs)<2:continue
            scores=[len(query&set(words(p.get_text(' ',strip=True))))/len(query) for p in paragraphs]
            best=max(range(len(scores)),key=lambda i:(scores[i],-i))
            if best and scores[best]>scores[0]:
                chosen=(paragraphs[0],paragraphs[best]);break
        if chosen is None:return None,'No later direct-sibling paragraph with better query coverage'
        first,best=chosen;first.insert_before(best.extract())
        detail='Move a better-matching existing paragraph before its first eligible sibling, within the same parent.'
    elif action=='split_long_paragraph':
        candidates=[p for p in soup.find_all('p') if not p.find_parent(['nav','header','footer','aside']) and not p.find() and len(words(p.get_text()))>100]
        chosen=None
        for p in candidates:
            text=p.get_text();boundaries=list(re.finditer(r'(?<=[.!?])\s+',text))
            if not boundaries:continue
            boundary=min(boundaries,key=lambda m:abs(m.start()-len(text)/2))
            left,right=text[:boundary.start()],text[boundary.end():]
            if min(len(words(left)),len(words(right)))>=20:
                chosen=(p,left,right);break
        if chosen is None:return None,'No long plain-text paragraph with an interior sentence boundary'
        p,left,right=chosen;p.string=left
        new=soup.new_tag('p');new.attrs={k:v for k,v in p.attrs.items() if k!='id'};new.string=right;p.insert_after(new)
        detail='Split one long plain-text paragraph at an existing sentence boundary; preserve word order.'
    else:raise ValueError(action)
    assert body_words(soup)==body_before,'Edit changed the visible body word multiset'
    return str(soup),detail
