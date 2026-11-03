import test from 'node:test';import assert from 'node:assert/strict';
import {chunkText,vector,quality,collectionName} from '../lib.mjs';
test('chunking preserves Unicode code points and avoids trailing duplicate overlap',()=>{assert.deepEqual(chunkText('a😀bcde',4,1),['a😀bc','cde']);assert.deepEqual(chunkText('abcd',4,1),['abcd']);assert.deepEqual(chunkText('  '),[]);});
test('reject malformed model output and SQL identifiers',()=>{assert.throws(()=>vector(Array(384).fill(NaN)));assert.throws(()=>vector(Array(384).fill(0)));assert.throws(()=>collectionName('x`; DROP TABLE'));assert.equal(vector(Array(384).fill(.1)).length,384);});
test('quality treats duplicate IDs as one hit and accounts for missed relevance',()=>{assert.deepEqual(quality(['a','a'],['a','b'],2),{recall:.5,ndcg:1/(1+1/Math.log2(3))});});
