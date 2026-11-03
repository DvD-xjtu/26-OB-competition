import {pipeline,env} from '@huggingface/transformers';
import ortModule from '../node_modules/@huggingface/transformers/dist/ort-wasm-simd-threaded.jsep.mjs?url';
import ortWasm from '../node_modules/@huggingface/transformers/dist/ort-wasm-simd-threaded.jsep.wasm?url';
import {MODEL} from '../lib.mjs';
env.allowLocalModels=false;
env.backends.onnx.wasm.wasmPaths={mjs:ortModule,wasm:ortWasm};
let encoder,backend,precision;
const revision='751bff37182d3f1213fa05d7196b954e230abad9';
self.onmessage=async({data})=>{
  const {id,type,texts,dtype='q8',device='auto'}=data;
  try {
    if(type==='load') {
      if(encoder)await encoder.dispose();encoder=null;
      const start=performance.now(); let adapter;
      if(device==='auto'&&self.navigator.gpu)adapter=await self.navigator.gpu.requestAdapter();
      backend=adapter?'webgpu':'wasm'; precision=dtype;
      const assets=new Map();
      const options={dtype,revision,device:backend,progress_callback:p=>{
        if(p.file){const previous=assets.get(p.file)||{file:p.file,startedMs:performance.now()-start};assets.set(p.file,{...previous,...(p.total?{bytes:p.total}:{}),status:p.status,...(p.status==='done'?{finishedMs:performance.now()-start}:{})});}
        self.postMessage({type:'progress',progress:p});
      }};
      let fallbackReason=null;
      try{encoder=await pipeline('feature-extraction',MODEL,options);}
      catch(error){if(backend!=='webgpu')throw error;fallbackReason=error.message;backend='wasm';encoder=await pipeline('feature-extraction',MODEL,{...options,device:'wasm'});}
      self.postMessage({id,backend,dtype:precision,model:MODEL,revision,loadMs:performance.now()-start,fallbackReason,assets:[...assets.values()]});
    }else{
      if(!encoder)throw new Error('请先加载模型');
      const start=performance.now(); const result=await encoder(texts,{pooling:'mean',normalize:true});
      self.postMessage({id,embeddings:result.tolist(),embeddingMs:performance.now()-start,backend,dtype:precision});
    }
  }catch(error){self.postMessage({id,error:error.message});}
};
