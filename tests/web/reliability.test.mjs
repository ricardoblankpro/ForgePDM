import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {createRevision} from '../../src/forgepdm/web/reliability.mjs';
globalThis.crypto ??= webcrypto;
const values = new Map();
const storage = {getItem:key=>values.get(key), setItem:(key,value)=>values.set(key,value)};
const results = new Map();
let posts = 0;
let lost = true;
let first;
const api = {async request(path, options) {
  if(path==='/auth/me') return {id:'actor'};
  if(!options) {
    const result=results.get(path.split('/').at(-1));
    if(!result) throw Object.assign(new Error('missing'),{status:404});
    return result;
  }
  posts++;
  first ??= options.body;
  assert.deepEqual(options.body,first);
  assert.equal(path,'/items/item/revisions/recoverable');
  const result={id:'revision-B',item_id:'item'};
  results.set(options.body.operation_id,result);
  if(lost) {lost=false;throw new Error('response lost');}
  return result;
}};
await assert.rejects(()=>createRevision(api,'item','revision-A',()=> 'Original note',storage),/response lost/);
assert.equal(posts,1);
const result=await createRevision(api,'item','revision-A',()=>{throw new Error('must not prompt again');},storage);
assert.equal(result.id,'revision-B');
assert.equal(posts,1);
assert.equal(JSON.parse([...values.values()][0]).change_note,'Original note');
assert(![...values.values()][0].includes('access_token'));
// A canceled operation leaves no durable intent.
assert.equal(await createRevision(api,'other','revision-A',()=>null,storage),null);
assert.equal(values.size,1);
// Corrupt local state never starts a different operation.
const key=[...values.keys()][0];
values.set(key,JSON.stringify({actor:'someone-else'}));
await assert.rejects(()=>createRevision(api,'item','revision-A',()=> 'New note',storage),/preserved/);
assert.equal(posts,1);
