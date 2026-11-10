import assert from 'node:assert/strict';
import test from 'node:test';
import {materialsUI} from '../../src/forgepdm/web/materials.mjs';
function element(tag,attrs={},...children) {
 return {tag,attrs,children,isConnected:true,classList:{add(){}},append(...nodes){this.children.push(...nodes);},replaceChildren(...nodes){this.children=nodes;}};
}
function text(node) {return typeof node==='string'?node:(node.children||[]).map(text).join('\n');}
for (const incomplete of [false,true]) test(`Assembly mass renders ${incomplete?'missing component and subtotal':'complete total and estimate warning'}`,async()=>{
 const host=element('div');
 const mass={mass_kg:incomplete?null:'1.25',known_mass_kg:'1.25',contains_cad_estimates:!incomplete,issues:incomplete?[{item_number:'P000001',revision_label:'A',quantity:'2',reason:'No uploaded native geometry'}]:[]};
 const api={request:async path=>path.endsWith('/assembly-mass')?mass:path.endsWith('/checkout')?null:{description:'Assembly'}};
 const ui=materialsUI({api,el:element,button:(label)=>element('button',{},label),state:{user:{id:'viewer'}}});
 await ui.render(host,{number:'A000001'},{id:'revision',lifecycle_state:'released'});
 const result=text(host);
 assert.match(result,/stored engineering BOM/i);
 assert.match(result,/Refresh mass/);
 if(incomplete){assert.match(result,/Total unavailable. Known subtotal: 1.25 kg/);assert.match(result,/P000001-A × 2: No uploaded native geometry/);assert.doesNotMatch(result,/Total: 1.25/);}
 else {assert.match(result,/Total: 1.25 kg/);assert.match(result,/estimated fastener mass/);}
});
