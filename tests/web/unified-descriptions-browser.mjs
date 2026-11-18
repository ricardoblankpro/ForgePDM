// Disposable tests/web/serve.py fixture only.
import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const directory=process.argv[2];
const c=JSON.parse(await readFile(`${directory}/connection.json`,'utf8'));
const {chromium}=await import(pathToFileURL(process.env.FORGEPDM_PLAYWRIGHT));
const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
const page=await browser.newPage();
const checks=[],errors=[];
page.on('pageerror',e=>errors.push(e.message));
const check=(name,value=true)=>{assert.ok(value,name);checks.push(name);};
try {
 await page.goto(c.url+'/app/');
 await page.locator('#username').fill('web-admin');await page.locator('#password').fill(c.password);
 const login=page.waitForResponse(r=>r.url().endsWith('/auth/login')&&r.status()===200);
 await page.locator('#login-button').click();
 const token=(await(await login).json()).access_token;
 async function api(path,body){const r=await fetch(c.url+'/api/v1'+path,{method:body?'POST':'GET',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});assert.ok(r.ok,await r.clone().text());return r.json();}
 async function create(series,text,extra={}){return api('/items',{kind:series==='A'?'assembly':'part',number_series:series,name:text,description:text,project_id:['P','A'].includes(series)?c.projects.design:undefined,source_language:'en',...extra});}
 async function open(item){await page.evaluate(id=>{location.hash=new URLSearchParams({item:id}).toString();},item.id);await page.getByRole('tab',{name:'Description',exact:true}).click();}
 const p=await create('P','Clamp'),m=await create('M','QA STEEL PLATE 6 MM');
 await open(p);
 await page.getByLabel('Component description',{exact:true}).fill('Manual clamp');
 await page.getByRole('button',{name:'Save description',exact:true}).click();
 await page.getByLabel('Component description',{exact:true}).filter({visible:true}).waitFor();
 await page.locator('.detail-name').filter({hasText:'Manual clamp'}).waitFor();
 check('P manual description is shown consistently');
 await page.getByLabel('Find raw material',{exact:true}).fill(m.number);
 await page.getByRole('button',{name:'Search materials',exact:true}).click();
 await page.getByRole('button',{name:`${m.number} — QA STEEL PLATE 6 MM`,exact:true}).click();
 await page.locator('.detail-name').filter({hasText:'QA STEEL PLATE 6 MM'}).waitFor();
 check('P material assignment replaces manual text');
 await page.getByLabel('Component description',{exact:true}).waitFor({state:'detached'});
 check('assigned P has no independent text editor');
 await page.getByRole('button',{name:'Clear material',exact:true}).click();
 await page.getByLabel('Component description',{exact:true}).waitFor();
 check('clearing material clears text',await page.getByLabel('Component description',{exact:true}).inputValue()==='');
 await page.locator('.detail-name').filter({hasText:'No description assigned.'}).waitFor();
 check('cleared description does not fall back to legacy name');
 const a=await create('A','QA Assembly');await open(a);
 await page.getByLabel('Assembly description',{exact:true}).waitFor();check('A has one assembly editor');
 const s=await create('S','QA Purchased sensor');await open(s);
 await page.getByLabel('Purchasing description',{exact:true}).waitFor();
 await page.getByRole('heading',{name:'Standard part mass',exact:true}).waitFor();check('generic S description coexists with mass controls');
 await open(m);await page.getByLabel('Material description',{exact:true}).waitFor();check('M has one material editor');
 const structured=(await api('/items?q=ISO4029&number_series=S')).items[0] || await create('S','Legacy submitted name',{standard_specification:{geometry:{Type:'ISO4029',Diameter:'M7',Length:'13'},material:'steel',grade:'45H',finish:'plain'}});
 await open(structured);await page.getByText('Description fixed by purchasing specification.',{exact:true}).waitFor();
 check('structured S description is read only');
 const record=await api(`/revisions/${structured.current_revision_id}/description`);
 check('structured S derives canonical text',record.description.includes('ISO4029')&&record.description.includes('45H'));
 await page.getByRole('tab',{name:'Translations',exact:true}).click();
 await page.getByRole('heading',{name:'description',exact:true}).waitFor();
 check('only one translation editor',await page.locator('#tab-content textarea').count()===1);
 check('legacy text remains accessible',await page.getByText('Historical item text',{exact:true}).count()===1);
 check('no JavaScript errors',errors.length===0);
 await writeFile(`${directory}/unified-descriptions-browser-report.json`,JSON.stringify({checks,errors,scope:'Disposable database only'},null,2));
 console.log(`Unified description browser QA passed: ${checks.length} checks.`);
} finally {await browser.close();}
