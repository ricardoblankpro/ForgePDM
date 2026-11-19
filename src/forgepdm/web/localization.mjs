// One revision description; translation editing never changes engineering text.
const LANGUAGES = {en:'English','pt-BR':'Português (Brasil)'};
const languageName = value => LANGUAGES[value] || 'Unknown';

export function defaultTranslationLanguage(sourceLanguage, displayLanguage='en') {
  return sourceLanguage==='en'?'pt-BR':sourceLanguage==='pt-BR'?'en':LANGUAGES[displayLanguage]?displayLanguage:'en';
}

export function translationView(source, language, text) {
  const active=source.translations.filter(t=>t.language===language&&!t.superseded_at);
  const approved=active.findLast(t=>t.state==='approved'&&t.source_version===source.current_version);
  const draft=active.findLast(t=>t.state==='draft'&&t.source_version===source.current_version);
  const record=draft||approved||active.at(-1);
  const saved=record?.text||'';
  const dirty=text!==saved;
  const review=record?.state==='needs_review'||!!record&&record.source_version!==source.current_version;
  const status=dirty?'Unsaved changes':review?'Needs review':draft?'Draft saved':approved?'Approved':'Not translated';
  return {approved,draft,record,saved,dirty,review,status};
}

export function localizationUI({api,el,button,onChange=()=>{}}) {
  let epoch=0;
  const buffers=new Map(),targets=new Map();
  const reset=()=>{epoch++;buffers.clear();targets.clear();};
  window.addEventListener('beforeunload',event=>{if(buffers.size){event.preventDefault();event.returnValue='';}});
  async function render(host,item,revision) {
    const generation=++epoch;
    const valid=()=>generation===epoch&&host.isConnected;
    host.replaceChildren(el('p',{class:'loading',role:'status'},'Loading translations…'));
    try {
      const sources=await api.request(`/items/${item.id}/localized-texts?revision_id=${revision.id}`);
      if(!valid())return;
      const source=sources.find(s=>s.field==='description');
      if(!source){host.replaceChildren(el('p',{},'No revision description is available to translate.'));return;}
      let language=targets.get(source.id)||defaultTranslationLanguage(source.source.language,api.language);
      if(language===source.source.language)language=defaultTranslationLanguage(source.source.language);
      targets.set(source.id,language);
      const key=`${source.id}:${language}`;
      let busy=false,assistance=null;
      const initial=translationView(source,language,'');
      const text=el('textarea',{id:'translation-text','aria-label':`${languageName(language)} translation`,maxlength:1000,rows:5,placeholder:`Enter the description in ${languageName(language)}…`,value:buffers.get(key)?.text??initial.saved});
      if(text.value===initial.saved)buffers.delete(key);
      const badge=el('span',{class:'translation-state',role:'status'});
      const hint=el('p',{class:'translation-hint','aria-live':'polite'});
      const proposalWarning=el('p',{class:'translation-source-warning',hidden:true});
      const error=el('p',{class:'translation-error',role:'alert',hidden:true});
      const reload=button('Reload latest state',()=>render(host,item,revision),{class:'secondary',hidden:true});
      const currentText=el('p',{class:'translation-current-text'});
      const current=el('div',{class:'translation-current',hidden:true},el('span',{class:'translation-caption'},`Currently displayed in ${languageName(language)}`),currentText);
      const save=button('Save draft',()=>change('draft'),{class:'primary'});
      const approve=button('Approve translation',()=>change('approve'),{class:'primary'});
      const discard=button('Discard changes',()=>{text.value=translationView(source,language,text.value).saved;buffers.delete(key);update();},{class:'quiet'});
      const suggestion=button('',()=>change('generate'),{class:'secondary',hidden:true});
      const suggestionArea=el('div',{class:'translation-assistance'},suggestion);
      const sourceSelect=el('select',{'aria-label':'Original language'},...Object.entries(LANGUAGES).map(([value,label])=>el('option',{value},label)));
      sourceSelect.value=LANGUAGES[source.source.language]?source.source.language:'';
      if(!sourceSelect.value){sourceSelect.prepend(el('option',{value:''},'Choose the original language…'));sourceSelect.value='';}
      const confirm=button(source.source.language==='und'?'Confirm original language':'Correct original language',()=>change('correct-language',sourceSelect.value),{class:'secondary'});
      const correction=el('details',{class:'translation-source-settings'},el('summary',{},'Original language settings'),el('p',{},'This labels the original text; it does not translate it. Changing it marks existing translations as needing review.'),el('label',{},'Original language',sourceSelect),confirm);
      if(source.source.language==='und')correction.open=true;
      const warning=el('p',{class:'translation-source-warning',hidden:source.source.language!=='und'},'Confirm the original language below before approving a translation. You can save a draft first.');
      const heading=el('h3',{},`${languageName(language)} translation`);
      const choices=Object.keys(LANGUAGES).filter(value=>value!==source.source.language);
      let picker=null;
      if(choices.length>1){
        picker=el('select',{'aria-label':'Translation language',onChange:()=>{targets.set(source.id,picker.value);render(host,item,revision);}},...choices.map(value=>el('option',{value},languageName(value))));picker.value=language;
      }
      const editor=el('section',{class:'translation-editor','aria-label':'Translation editor'},
        el('div',{class:'translation-panel-heading'},el('div',{},heading,el('p',{class:'translation-caption'},`Target language · ${languageName(language)}`)),badge),
        ...(picker?[el('label',{class:'translation-target'},'Translate into',picker)]:[]),text,suggestionArea,hint,proposalWarning,current,
        el('div',{class:'translation-actions'},discard,save,approve),error,reload);
      const origin=revision.description_record?.material_revision_id?'From assigned material':item.standard_specification?'From purchasing specification':item.number.startsWith('M')?'Material description':'Original revision description';
      const original=el('section',{class:'translation-original','aria-label':'Original description'},el('div',{class:'translation-panel-heading'},el('div',{},el('h3',{},'Original description'),el('p',{class:'translation-caption'},languageName(source.source.language))),el('span',{class:'translation-state'},'Original')),el('p',{class:'translation-original-text'},source.source.text||'No description assigned.'),el('p',{class:'translation-caption'},origin));
      const history=el('details',{class:'translation-history'},el('summary',{},'Source details & translation history'),correction,
        el('h4',{},'Original text history'),...source.history.map(v=>el('p',{},`${languageName(v.language)} · ${v.created_at.slice(0,10)}: ${v.text||'(empty)'}`)),
        el('h4',{},'Translation history'),...source.translations.map(t=>historyRow(t)));
      if(!source.translations.length)history.append(el('p',{},'No translations saved.'));
      const legacy=sources.filter(s=>s.field!=='description');
      if(legacy.length)history.append(el('details',{},el('summary',{},'Historical item text'),...legacy.map(s=>el('div',{},el('h4',{},s.field==='designation'?'Previous item name':'Previous general description'),...s.history.map(v=>el('p',{},`${languageName(v.language)}: ${v.text||'(empty)'}`)),...s.translations.map(historyRow)))));
      host.replaceChildren(el('div',{class:'translation-workspace'},el('h2',{},'Translate description'),el('p',{class:'translation-intro'},`${item.number} · Revision ${revision.label}`),warning,el('div',{class:'translation-columns'},original,editor),history));
      // Unconfirmed sources need an obvious, reachable confirmation control.
      if(source.source.language==='und')history.open=true;
      if(!source.can_edit)editor.prepend(el('p',{class:'translation-access'},'View only. Edit access is required to save or approve translations.'));
      function historyRow(t){
        const names={draft:'Draft saved',approved:'Approved',needs_review:'Needs review'};
        const row=el('div',{class:'translation-history-entry'},el('p',{},`${languageName(t.language)} · ${t.superseded_at?'Superseded':names[t.state]||t.state} · ${t.created_at.slice(0,10)}`),el('p',{},t.text));
        let provenance={};try{provenance=JSON.parse(t.provenance_json);}catch{/* Optional older metadata. */}
        const warnings=provenance.warnings||[];
        if(warnings.length)row.append(el('p',{class:'translation-source-warning'},'Review these untranslated or unspecified terms: '+warnings.join('; ')));
        return row;
      }
      function update(){
        const view=translationView(source,language,text.value);
        let provenance={};try{provenance=JSON.parse(view.record?.provenance_json||'{}');}catch{/* Older metadata. */}
        const warnings=provenance.warnings||[];
        proposalWarning.hidden=!warnings.length;
        proposalWarning.textContent='Review these untranslated or unspecified terms: '+warnings.join('; ');
        const editable=source.can_edit&&!busy&&!!source.source.text;
        text.readOnly=!editable;
        badge.textContent=busy?'Saving…':view.status;badge.dataset.state=view.status;
        save.disabled=!editable||!text.value.trim()||!view.dirty&&!view.review;
        approve.hidden=!view.draft;approve.disabled=!editable||view.dirty||source.source.language==='und';
        save.className=view.draft&&!view.dirty?'secondary':'primary';
        discard.hidden=!view.dirty;discard.disabled=busy;
        suggestion.disabled=!editable||view.dirty;suggestion.hidden=!assistance;
        sourceSelect.disabled=!source.can_edit||busy||view.dirty;
        confirm.disabled=!source.can_edit||busy||view.dirty||!sourceSelect.value||sourceSelect.value===source.source.language;
        if(picker)picker.disabled=busy;
        current.hidden=!view.approved||!view.dirty&&!view.draft;
        currentText.textContent=view.approved?.text||'';
        hint.textContent=!source.source.text?'Add a description in the Description tab before translating.':view.dirty?(view.approved?'Your approved translation stays in use until this edit is approved.':'Save this draft, then review and approve it.'):view.review?'The original or its language changed. Review this text and save a new draft.':view.draft?'Draft saved. Review the text, then approve it to display it.':view.approved?`Approved. Available when viewing ${languageName(language)} descriptions.`:`No ${languageName(language)} translation yet. The original description is shown.`;
        if(buffers.get(key)?.sourceVersion!==undefined&&buffers.get(key).sourceVersion!==source.current_version)hint.textContent+=' Your unsaved text was kept; compare it with the latest original before saving.';
      }
      text.addEventListener('input',()=>{
        const view=translationView(source,language,text.value);
        if(view.dirty)buffers.set(key,{text:text.value,sourceVersion:source.current_version});else buffers.delete(key);
        update();
      });
      sourceSelect.addEventListener('change',update);
      async function change(operation,locale=language){
        if(busy||!source.can_edit)return;
        const view=translationView(source,language,text.value);
        if(operation==='approve'&&(!view.draft||view.dirty))return;
        if((operation==='generate'||operation==='correct-language')&&view.dirty)return;
        busy=true;error.hidden=true;reload.hidden=true;update();
        try{
          await api.request(`/localized-texts/${encodeURIComponent(source.id)}`,{method:'POST',body:{operation,expected_token:source.token,language:locale,text:text.value,translation_id:operation==='approve'?view.draft.id:undefined}});
          buffers.delete(key);
          if(valid()){await render(host,item,revision);Promise.resolve(onChange(item,revision)).catch(()=>{});}
        }catch(failure){
          if(!valid())return;
          error.textContent=failure.status===409?'The original or translations changed. Your text is kept. Reload the latest state, review it and save again.':failure.message;
          error.hidden=false;reload.hidden=failure.status!==409;
        }finally{busy=false;if(valid())update();}
      }
      update();
      if(source.can_edit&&source.source.text){
        api.request(`/localized-texts/${encodeURIComponent(source.id)}/proposal-availability?language=${encodeURIComponent(language)}`).then(result=>{
          if(!valid())return;
          if(result.available){assistance=result;suggestion.textContent=result.label;update();}
        }).catch(()=>{/* Manual editing remains usable when assistance cannot be checked. */});
      }
    }catch(failure){if(valid())host.replaceChildren(el('p',{class:'translation-error',role:'alert'},failure.message),button('Try again',()=>render(host,item,revision),{class:'secondary'}));}
  }
  return {render,reset};
}
