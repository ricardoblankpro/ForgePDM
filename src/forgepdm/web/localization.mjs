// All strings are presentation text; legacy CAD/source values are never replaced.
export function localizationUI({api,el,button}) {
 let epoch=0;
 async function render(host,item,revision) {
  const generation=++epoch;
  const language=api.language;
  host.replaceChildren(el('p',{},'Loading translations…'));
  try {
   const sources=await api.request(`/items/${item.id}/localized-texts?revision_id=${revision.id}`);
   if(generation!==epoch||!host.isConnected)return;
   host.replaceChildren();
   for(const source of sources) {
    const section=el('section',{}), text=el('textarea',{'aria-label':`${source.field} translation`,maxlength:1000});
    const active=source.translations.filter(t=>t.language===language&&!t.superseded_at);
    text.value=active.at(-1)?.text||'';
    const status=el('p',{},active.at(-1)?.state||'missing');
    const change=async(operation,id)=>{
     try {
      if(operation==='approve'&&text.value.trim()!==source.translations.find(t=>t.id===id)?.text)throw new Error('Save changes as a draft before approving.');
      await api.request(`/localized-texts/${encodeURIComponent(source.id)}`,{method:'POST',body:{operation,expected_token:source.token,language,text:text.value,translation_id:id}});await render(host,item,revision);}
     catch(error){status.textContent=error.message;}
    };
    section.append(el('h3',{},source.field),el('p',{},`${source.source.language}: ${source.source.text}`),status,text,
     button('Save draft',()=>change('draft')),button('Generate proposal',()=>change('generate')),
     button('Confirm/correct source language',()=>change('correct-language')));
    for(const translation of active) {
     section.append(el('p',{},`${translation.language} · ${translation.state}: ${translation.text}`),el('pre',{},translation.provenance_json));
     if(translation.state==='draft')section.append(button('Approve',()=>change('approve',translation.id)));
    }
    text.readOnly=!source.can_edit;
    for(const control of section.querySelectorAll('button'))control.disabled=!source.can_edit;
    host.append(section);
   }
  } catch(error){if(generation===epoch&&host.isConnected)host.replaceChildren(el('p',{role:'alert'},error.message));}
 }
 return {render};
}
