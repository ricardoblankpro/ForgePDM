import test from 'node:test';
import assert from 'node:assert/strict';
import {defaultTranslationLanguage,translationView} from '../../src/forgepdm/web/localization.mjs';

test('target language is independent of browsing language and excludes the original',()=>{
 assert.equal(defaultTranslationLanguage('pt-BR','pt-BR'),'en');
 assert.equal(defaultTranslationLanguage('en','en'),'pt-BR');
 assert.equal(defaultTranslationLanguage('und','pt-BR'),'pt-BR');
});

test('draft replacement preserves approval until a saved draft is approved',()=>{
 const source={current_version:2,translations:[
  {id:'approved',language:'en',text:'Plate',state:'approved',source_version:2},
  {id:'draft',language:'en',text:'Steel plate',state:'draft',source_version:2},
  {id:'old',language:'en',text:'Old text',state:'approved',source_version:1,superseded_at:'date'}
 ]};
 const unsaved=translationView(source,'en','Revised steel plate');
 assert.equal(unsaved.status,'Unsaved changes');assert.equal(unsaved.approved.text,'Plate');
 assert.equal(translationView(source,'en','Steel plate').status,'Draft saved');
 source.translations[1].state='needs_review';source.current_version=3;
 const stale=translationView(source,'en','Steel plate');
 assert.equal(stale.status,'Needs review');assert.equal(stale.approved,undefined);
});
