export const DIMENSION = 384;
export const MODEL = 'Xenova/all-MiniLM-L6-v2';
export function collectionName(value) {
  if (typeof value !== 'string' || !/^[a-z][a-z0-9_]{0,39}$/.test(value)) throw new Error('知识库名须以小写字母开头，最多40位，仅含字母、数字、下划线');
  return `local_kb_${value}`;
}
export function vector(value) {
  if (!Array.isArray(value) || value.length !== DIMENSION || !value.every(Number.isFinite) || !value.some(x=>x!==0)) throw new Error('向量必须包含384个有限数值且不能全零');
  return value;
}
export function chunkText(text, limit=900, overlap=120) {
  if (!Number.isInteger(limit) || limit < 1 || overlap < 0 || overlap >= limit) throw new Error('invalid chunk settings');
  const chars = Array.from(text.trim()); const chunks=[];
  for(let start=0;start<chars.length;start+=limit-overlap) {
    chunks.push(chars.slice(start,start+limit).join(''));
    if(start+limit>=chars.length) break;
  }
  return chunks;
}
export function quality(ids, relevant, k=5) {
  const truth=new Set(relevant); const ranked=[...new Set(ids)].slice(0,k);
  const hits=ranked.filter(id=>truth.has(id)).length;
  const dcg=ranked.reduce((sum,id,i)=>sum+(truth.has(id)?1/Math.log2(i+2):0),0);
  const ideal=Array.from({length:Math.min(k,truth.size)},(_,i)=>1/Math.log2(i+2)).reduce((a,b)=>a+b,0);
  return {recall:truth.size?hits/truth.size:0,ndcg:ideal?dcg/ideal:0};
}
