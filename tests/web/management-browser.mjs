// Writes only to the disposable fixture created by tests/web/serve.py.
import assert from "node:assert/strict";
import {readFile,writeFile} from "node:fs/promises";
import path from "node:path";
import {pathToFileURL} from "node:url";
const directory=process.argv[2];
if(!directory)throw new Error("Pass the disposable fixture directory");
const config=JSON.parse(await readFile(path.join(directory,"connection.json"),"utf8"));
const {chromium}=await import(pathToFileURL(process.env.FORGEPDM_PLAYWRIGHT||"/tmp/forgepdm-web-qa/node_modules/playwright-core/index.mjs"));
const browser=await chromium.launch({executablePath:process.env.FORGEPDM_BROWSER||"/usr/bin/google-chrome",headless:true,args:["--no-sandbox","--disable-dev-shm-usage"]});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
const page=await context.newPage();
const second=await browser.newContext();const userPage=await second.newPage();
const report={browser:browser.version(),scope:"Disposable real API/database and Chrome; no user engineering data",checks:[],errors:[]};
for(const opened of [page,userPage])opened.on("pageerror",error=>report.errors.push(error.message));
const check=(label,value=true)=>{assert.ok(value,label);report.checks.push(label);};
const modal=()=>page.locator("dialog");
async function login(opened,username,password){
 await opened.goto(config.url+"/app/");await opened.locator("#username").fill(username);await opened.locator("#password").fill(password);
 const result=opened.waitForResponse(r=>r.url().endsWith("/auth/login")&&r.status()===200);
 await opened.locator("#login-button").click();const body=await(await result).json();await opened.locator("#workspace").waitFor({state:"visible"});return body.access_token;
}
async function save(label){await modal().getByRole("button",{name:label,exact:true}).click();await modal().waitFor({state:"detached"});}
async function jsonCall(token,url,method="GET",body){const response=await context.request.fetch(config.url+"/api/v1"+url,{method,headers:{Authorization:`Bearer ${token}`},...(body?{data:body}:{})});assert.ok(response.ok(),`${method} ${url} ${response.status()}`);return response.status()===204?null:response.json();}
try{
 const admin=await login(page,"web-admin",config.password);
 await page.locator("#nav-users").click();await page.getByRole("button",{name:"Create user",exact:true}).click();
 await modal().getByLabel("Username",{exact:true}).fill("qa.operator");await modal().getByLabel("Display name").fill("QA Operator");await modal().getByLabel("Temporary password").fill("1234");await save("Create user");
 await page.getByRole("row").filter({hasText:"qa.operator"}).waitFor();check("admin creates account with required password change");
 const users=await jsonCall(admin,"/admin/users");const operator=users.items.find(row=>row.username==="qa.operator");
 const own=page.getByRole("row").filter({hasText:"web-admin"});await own.getByRole("button",{name:"Edit",exact:true}).click();await modal().getByLabel("Account enabled").uncheck();await modal().getByRole("button",{name:"Save user"}).click();await modal().getByRole("alert").waitFor();check("self-disable is rejected inline without losing the form");await modal().getByRole("button",{name:"Cancel",exact:true}).click();
 await page.locator("#nav-project-settings").click();await page.getByRole("button",{name:"Create project",exact:true}).click();
 await modal().getByLabel("Project number").fill("PRJ-MGMT");await modal().getByLabel("Name",{exact:true}).fill("Management test");await modal().getByLabel("Customer",{exact:true}).fill("Customer <script>test</script>");await modal().getByLabel("Due date").fill("2026-12-15");await modal().getByLabel("Description").fill("Test delivery scope");await save("Save project");
 let row=page.getByRole("row").filter({hasText:"PRJ-MGMT"});await row.waitFor();check("admin creates project with customer, due date and description");check("customer is rendered as text",await row.textContent().then(text=>text.includes("<script>test</script>")));
 await row.getByRole("button",{name:"Members",exact:true}).click();await modal().getByLabel("User",{exact:true}).selectOption(operator.id);await modal().getByLabel("Project role").selectOption("editor");await save("Set membership");
 check("admin assigns project membership through the GUI");
 const projects=await jsonCall(admin,"/management/projects");const project=projects.items.find(p=>p.project_number==="PRJ-MGMT");
 const temporary=await login(userPage,"qa.operator","1234");await userPage.getByRole("heading",{name:"Change your temporary password"}).waitFor();
 check("temporary-password login shows only password-change workspace",await userPage.locator("#nav-users").isHidden()&&await userPage.locator("#nav-catalog").isHidden());
 const restricted=await second.request.get(config.url+"/api/v1/items",{headers:{Authorization:`Bearer ${temporary}`}});check("temporary credentials cannot access engineering API",restricted.status()===403);
 await userPage.getByLabel("Current password",{exact:true}).fill("1234");await userPage.getByLabel("New password",{exact:true}).fill("5678");await userPage.getByLabel("Confirm new password").fill("5678");await userPage.getByRole("button",{name:"Change password",exact:true}).click();await userPage.locator("#login-screen").waitFor({state:"visible"});
 check("password change requires a fresh sign-in");
 const memberToken=await login(userPage,"qa.operator","5678");await userPage.locator("#nav-project-settings").click();let memberRow=userPage.getByRole("row").filter({hasText:"PRJ-MGMT"});await memberRow.waitFor();
 check("member sees assigned project properties and no administration buttons",await userPage.locator("#nav-users").isHidden()&&await userPage.getByRole("button",{name:"Create project",exact:true}).count()===0);
 await memberRow.getByRole("button",{name:"Details",exact:true}).click();check("member project properties are read only",await userPage.locator('dialog input[name="customer"]').isDisabled());await userPage.locator("dialog").getByRole("button",{name:"Cancel",exact:true}).click();
 const denied=await second.request.post(config.url+"/api/v1/admin/users",{headers:{Authorization:`Bearer ${memberToken}`},data:{username:"attack",display_name:"Attack",password:"1234"}});check("regular user cannot bypass hidden controls",denied.status()===403);
 await userPage.locator("#nav-activity").click();await userPage.getByRole("table",{name:"Activity history"}).waitFor();check("activity user picker is scoped to accessible events",await userPage.locator(`#field-actor_id option[value="${operator.id}"]`).count()===1 && !await userPage.locator("#field-actor_id").textContent().then(text=>text.includes("web-viewer")));
 const created=await jsonCall(admin,"/items","POST",{kind:"part",name:"Checkout dashboard fixture",project_id:project.id});
 await page.locator("#nav-checkouts").click();await page.locator("#management-panel").getByRole("button",{name:"Next →",exact:true}).click();const checkoutRow=page.getByRole("row").filter({hasText:"Checkout dashboard fixture"});await checkoutRow.waitFor();await checkoutRow.getByRole("button").click();await page.locator("#revision-picker").waitFor();check("my checkout links navigate to their exact revision",await page.locator("#revision-picker").inputValue()===created.current_revision_id);
 await page.locator("#nav-activity").click();await page.getByRole("table",{name:"Activity history"}).waitFor();await page.getByLabel("Exact action (optional)").fill("project.member_set");await page.getByRole("button",{name:"Filter",exact:true}).click();await page.getByRole("table",{name:"Activity history"}).getByRole("row").filter({hasText:"project.member_set"}).waitFor();check("activity filters return administrative audit events");
 await page.locator("#nav-users").click();await page.getByRole("row").filter({hasText:"qa.operator"}).getByRole("button",{name:"Reset password"}).click();await modal().getByLabel("Temporary password").fill("9012");await save("Reset password");await userPage.locator("#nav-checkouts").click();await userPage.locator("#login-screen").waitFor({state:"visible"});check("admin reset revokes an existing browser session");
 await login(userPage,"qa.operator","9012");await userPage.getByRole("heading",{name:"Change your temporary password"}).waitFor();check("reset password again requires mandatory change");
 await page.getByRole("row").filter({hasText:"qa.operator"}).getByRole("button",{name:"Edit",exact:true}).click();await modal().getByLabel("Account enabled").uncheck();await save("Save user");
 const disabled=await second.request.post(config.url+"/api/v1/auth/login",{data:{username:"qa.operator",password:"9012"}});check("disabled account cannot sign in",disabled.status()===401);
 await page.locator("#nav-project-settings").click();row=page.getByRole("row").filter({hasText:"PRJ-MGMT"});await row.getByRole("button",{name:"Edit properties"}).click();await modal().getByLabel("Archived",{exact:true}).check();await save("Save project");row=page.getByRole("row").filter({hasText:"PRJ-MGMT"});check("archive preserves project and removes active catalog option",(await row.textContent()).includes("Archived")&&await page.locator(`#project-filter option[value="${project.id}"]`).count()===0);
 await row.getByRole("button",{name:"Members",exact:true}).click();await modal().getByRole("button",{name:"Remove",exact:true}).click();await save("Remove membership");check("admin can remove project membership");
 const events=await jsonCall(admin,"/activity?action=user.password_reset");check("audit contains reset events without credentials",events.items.some(e=>e.entity_id===operator.id)&&!JSON.stringify(events).includes("9012"));
 check("tokens and credentials stay out of persistent browser storage",await page.evaluate(()=>localStorage.length===0&&sessionStorage.length===0));
 await page.getByRole("table",{name:"Project properties"}).waitFor();
 await page.screenshot({path:path.join(directory,"management-desktop.png"),fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(directory,"management-mobile.png"),fullPage:true});check("mobile management page fits viewport",await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 check("no uncaught browser exceptions",report.errors.length===0);report.status="passed";
}catch(error){report.status="failed";report.failure=error.message;throw error;}
finally{await writeFile(path.join(directory,"management-report.json"),JSON.stringify(report,null,2)+"\n");await browser.close();}
console.log(`Management browser verification: ${report.checks.length} checks passed`);
