import express from 'express';
import {SeekdbClient,Schema,VectorIndexConfig,FulltextIndexConfig} from 'seekdb';
import {collectionName,vector,DIMENSION} from './lib.mjs';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=path.dirname(fileURLToPath(import.meta.url));
const client=new SeekdbClient(process.env.SEEKDB_PATH ? {path:process.env.SEEKDB_PATH,database:process.env.SEEKDB_DATABASE||'test'} : {
  host:process.env.SEEKDB_HOST||'127.0.0.1',port:Number(process.env.SEEKDB_PORT||2881),user:process.env.SEEKDB_USER||'root',password:process.env.SEEKDB_PASSWORD||'',database:process.env.SEEKDB_DATABASE||'test'});
const app=express();app.use(express.json({limit:'8mb'}));
const handles=new Map();
async function collection(name) {
  const key=collectionName(name);
  if(!handles.has(key)) {
    const pending=client.getOrCreateCollection({name:key,schema:new Schema({
      vectorIndex:new VectorIndexConfig({hnsw:{dimension:DIMENSION,distance:'cosine'},embeddingFunction:null}),
      fulltextIndex:new FulltextIndexConfig('ik',{ik_mode:'smart'})})});
    handles.set(key,pending); pending.catch(()=>handles.delete(key));
  }
  return handles.get(key);
}
app.get('/api/health',async(req,res)=>{await client.execute('SELECT 1');res.json({database:'seekdb',inference:'browser-only'});});
app.get('/api/libraries',async(req,res)=>res.json((await client.listCollections({withEmbeddingFunction:false})).map(x=>x.name).filter(x=>x.startsWith('local_kb_')).map(x=>x.slice(9))));
app.post('/api/libraries',async(req,res)=>{const c=await collection(req.body.name);res.json({name:req.body.name,count:await c.count()});});
app.post('/api/import',async(req,res)=>{
  const {name,documents}=req.body;
  if(!Array.isArray(documents)||!documents.length||documents.length>64) return res.status(400).json({error:'每批需要1–64个片段'});
  for(const d of documents) {
    if(typeof d.id!=='string'||d.id.length>100||!d.id||typeof d.text!=='string'||!d.text.trim()||d.text.length>12000||typeof d.source!=='string'||d.source.length>1000) return res.status(400).json({error:'无效文档'});
    vector(d.embedding);
  }
  if(new Set(documents.map(d=>d.id)).size!==documents.length) return res.status(400).json({error:'同一批不能重复ID'});
  const c=await collection(name); const start=performance.now();
  await c.upsert({ids:documents.map(d=>d.id),documents:documents.map(d=>d.text),embeddings:documents.map(d=>d.embedding),metadatas:documents.map(d=>({source:d.source,chunk:d.chunk??0}))});
  const written=performance.now(); await c.refresh_index();
  // Verify visibility with the database's own full-text/vector hybrid search.
  const deadline=performance.now()+15000;
  for(const d of documents) {
    let visible=false;
    while(performance.now()<deadline) {
      const r=await c.hybridSearch({query:{whereDocument:{$contains:d.text.slice(0,80)},nResults:64},knn:{queryEmbeddings:[d.embedding],nResults:64},nResults:64});
      if(r.ids[0]?.includes(d.id)){visible=true;break;}
      await new Promise(resolve=>setTimeout(resolve,150));
    }
    if(!visible) return res.status(503).json({error:'数据已写入，索引尚未确认可检索。请稍后重试同一批次。',written:documents.length});
  }
  res.json({count:await c.count(),writeMs:written-start,refreshMs:performance.now()-written});
});
app.post('/api/search',async(req,res)=>{
  const {name,text,embedding,k=5}=req.body; vector(embedding);
  if(typeof text!=='string'||!text.trim()||text.length>4000||!Number.isInteger(k)||k<1||k>50) return res.status(400).json({error:'无效查询'});
  const c=await collection(name);const start=performance.now();
  const result=await c.hybridSearch({query:{whereDocument:{$contains:text},nResults:Math.max(k,30)},knn:{queryEmbeddings:[embedding],nResults:Math.max(k,30)},rank:{rrf:{rankWindowSize:Math.max(k,30),rankConstant:60}},nResults:k,include:['documents','metadatas','distances']});
  res.json({result,searchMs:performance.now()-start});
});
app.use(express.static(path.join(root,'dist')));
app.use((error,req,res,next)=>{console.error(error.message);res.status(400).json({error:error.message});});
app.listen(Number(process.env.PORT||8787),'127.0.0.1',()=>console.log('Local knowledge: http://127.0.0.1:'+(process.env.PORT||8787)));
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,async()=>{await client.close();process.exit(0);});
