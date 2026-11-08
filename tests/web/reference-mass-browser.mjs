// Real browser check against the isolated live-supplier FreeCAD acceptance record.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
const directory=process.argv[2];
const {chromium}=await import(process.env.FORGEPDM_PLAYWRIGHT||"/tmp/forgepdm-material-web-qa/node_modules/playwright-core/index.mjs");
const config=JSON.parse(await fs.readFile(path.join(directory,"connection.json"),"utf8"));
const native=JSON.parse(await fs.readFile(path.join(directory,"reference-freecad-report.json"),"utf8"));
const browser=await chromium.launch({executablePath:"/usr/bin/google-chrome",headless:true,args:["--no-sandbox","--disable-dev-shm-usage"]});
const page=await browser.newPage({viewport:{width:1440,height:1050}});
const pageErrors=[],checks=[];page.on("pageerror",e=>pageErrors.push(e.message));
try{
 await page.goto(config.url+"/app/");
 await page.locator("#username").fill("web-admin");await page.locator("#password").fill(config.password);
 const login=page.waitForResponse(r=>r.url().endsWith("/auth/login")&&r.status()===200);
 await page.locator("#login-button").click();await login;
 await page.evaluate(item=>{location.hash=new URLSearchParams({item:item.id,revision:item.current_revision_id}).toString();},native.item);
 await page.waitForFunction(number=>document.querySelector(".detail-title-line h2")?.textContent===number,native.item.number);
 await page.getByRole("tab",{name:"Description",exact:true}).click();
 await page.getByText("16 g per piece",{exact:true}).waitFor();
 checks.push("S revision displays supplier mass per piece");
 assert.match(await page.locator("#tab-content").innerText(),/Fabory.*07015.080.030/);
 assert.match(await page.getByRole("link",{name:"Supplier source"}).getAttribute("href"),/^https:\/\/www\.fabory\.com\//);
 checks.push("source supplier, article, retrieval date and original product link are visible");
 assert.equal(await page.getByRole("button",{name:"Find reference mass",exact:true}).count(),0);
 checks.push("Released S revision offers no automatic mass write");
 await page.getByLabel("Import supplier reference CSV").setInputFiles({name:"invalid.csv",mimeType:"text/csv",buffer:Buffer.from("bad,columns\n1,2\n")});
 await page.getByRole("alert").filter({hasText:"CSV columns"}).waitFor();
 checks.push("invalid reference CSV reports validation without changing the saved mass");
 await page.setViewportSize({width:390,height:844});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 checks.push("reference view fits mobile viewport");
 assert.deepEqual(pageErrors,[]);
 await page.screenshot({path:path.join(directory,"reference-mass-mobile.png"),fullPage:true});
 await fs.writeFile(path.join(directory,"reference-browser-report.json"),JSON.stringify({checks,pageErrors},null,2));
 console.log(JSON.stringify({checks,pageErrors}));
}finally{await browser.close();}
