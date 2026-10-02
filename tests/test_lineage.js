// Offline interaction and escaping checks for the provenance tracker.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const unit={unit_id:'u1',request_id:'r1',shard:'embeddings/model/a.npy',shard_row:2,export_row:3,source_chunk_ids:['chunk1'],pool_member_ids:[]};
const record={hostname:'example.org',href:'https://example.org/item',prompt:'Question </script>',source_file:'part.parquet',source_row:4,snapshot_id:'snapshot1',quality_flags:['needs_review'],extraction_status:'needs_review',raw_path:'/data/raw/part.parquet',source_file_hash:'rawhash',payload_hash:'payloadhash',document_path:'/data/docs/snapshot1.json.gz',document_sha256:'dochash',document_blocks:2,document_chunks:1,extraction_id:'extraction1',query_unit_id:'query1',split:'train',upstream_exclusions:[],fields:[{field:'query',units:1,vectors:1,example:unit},{field:'page',units:1,vectors:1,example:{...unit,request_id:null,shard:null,pool_member_ids:['member1','member2']}}]};
const fixture={sample:true,records:[record],summary:{records:1,snapshots:1,run:'/data/run',raw_root:'/data/raw',preprocessed_root:'/data/prepared',preprocessing_pipeline:'markdownify',preprocessing_run_identity:'v1',embedding_serializer:'v3',model:{model:'text-embedding-3-large',dimensions:3072,vectors:2,unique_requests:1},cache_root:'/data/cache',joins:{raw_to_record:['source_file_hash','source_row']},artifacts:{},projection_fields:{},limitations:['Fixture only']}};
let html=fs.readFileSync(process.argv[2]||'representations/lineage_template.html','utf8');
if(!process.argv[2])html=html.replace('__LINEAGE_DATA__',JSON.stringify(fixture).replaceAll('<','\\u003c'));
const payload=html.match(/<script id="lineage-data" type="application\/json">([\s\S]*?)<\/script>/)[1];
const data=JSON.parse(payload),script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
assert(!payload.includes('</script>'));assert(!/<script[^>]+src=/.test(html));new vm.Script(script);
const element=(tag='div')=>({tag,textContent:'',value:'',children:[],events:{},append(...nodes){this.children.push(...nodes)},replaceChildren(){this.children=[]},addEventListener(name,fn){this.events[name]=fn}});
const elements=Object.fromEntries([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],element()]));elements['lineage-data'].textContent=JSON.stringify(data);
const document={getElementById:id=>{assert(elements[id],id);return elements[id]},createElement:element};
vm.runInNewContext(script,{document,JSON});
assert(elements.versions.textContent.includes('3072 dimensions'));assert(elements['record-detail'].textContent.includes('zero-based'));assert.equal(elements.fields.children.length,data.records[0].fields.length);
elements.search.value=data.records[0].snapshot_id;elements.search.events.input();assert(elements.choices.children.length>0);elements.choices.children[0].onclick();assert(elements['record-detail'].textContent.includes(data.records[0].snapshot_id));
elements.search.value='no-such-source-123456789';elements.search.events.input();assert.equal(elements.choices.children.length,0);
console.log('PASS: lineage search, source selection, field vector locations, offline scripts, and escaped source text.');
