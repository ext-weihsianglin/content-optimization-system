// Offline DOM-behavior check; does not substitute for visual browser review.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const html = fs.readFileSync(process.argv[2] || 'analysis/embedding-explorer.html', 'utf8');
const data = JSON.parse(html.match(/<script type="application\/json" id="data">([\s\S]*?)<\/script>/)[1]);
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(script);
assert(!/<script[^>]+src=/.test(html), 'Explorer must run without remote scripts');
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]);
assert.equal(new Set(ids).size, ids.length);
function element(tag = 'div') {
  return {tag, value:'',textContent:'',children:[],events:{},dataset:{},attributes:{},
    classList:{toggle(){}},namespaceURI:'http://www.w3.org/2000/svg',
    append(...nodes) {if(this.tag==='select' && !this.children.length && nodes[0]) this.value=nodes[0].value;this.children.push(...nodes)},
    replaceChildren(){this.children=[];if(this.tag==='select')this.value=''},
    setAttribute(name,value){this.attributes[name]=value},
    addEventListener(name,fn){this.events[name]=fn},
    querySelectorAll(tag){return this.children.filter(el=>el.tag===tag)}};
}
const elements=Object.fromEntries(ids.map(id=>[id,element(['map','host','label','quality','point','query','page-select','evidence-model'].includes(id)?'select':'div')]));
elements.data.textContent=JSON.stringify(data);
const document={getElementById:id=>{assert(elements[id],id);return elements[id]},createElement:element,createElementNS:(_,tag)=>element(tag)};
vm.runInNewContext(script,{document,JSON,URL});
function allText(el){return el.textContent+' '+el.children.map(allText).join(' ')}
assert.equal(elements.query.children.length,data.queries.length);
assert(allText(elements['page-summary']).includes('Original dataset label'));
assert(allText(elements.scores).includes('URL path'));
assert(allText(elements.supporting).includes('Best matching section'));
const excluded=data.queries.find(q=>q.results.every(r=>r.extraction_status!=='selected'));
if(excluded){elements.query.value=excluded.unit_id;elements.query.events.change();assert(allText(elements.scores).includes('not selected for content analysis'))}
elements.query.value=data.queries[0].unit_id;elements.query.events.change();
assert.equal(elements.plot.children.length,data.maps[0].points.length);
const last=data.maps[0].points.at(-1).unit_id;
elements.point.value=last;elements.point.events.change();
assert(elements.detail.children.some(el=>el.textContent.includes(last)));
if(data.maps.length>1){elements.map.value=data.maps[1].id;elements.map.events.change();assert.equal(elements.plot.children.length,data.maps[1].points.length)}
const host=data.maps[1]?.points[0]?.associations[0]?.hostname || data.maps[0].points[0]?.associations[0]?.hostname;
elements.host.value=host;elements.host.events.change();
assert(elements.plot.children.length>0);
elements.host.value='';elements.host.events.change();
assert(elements.plot.children.length>0);
console.log('PASS: query selection, readable evidence/scores, exclusions, optional maps, filtering, and offline scripts.');
