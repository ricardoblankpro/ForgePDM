// Controlled account/project operations. Tokens remain in the shared in-memory API.
export function managementUI(ctx) {
  const {state, request, api, el, button, dataTable, dateLabel, toast, navigate, resetSession, loadProjects} = ctx;
  const panel = document.querySelector("#management-panel");
  let version = 0;
  let dialog = null;
  let currentPage = "";
  const admin = () => state.user?.role === "admin" && !state.user.must_change_password;
  const errorBox = () => el("p", {class: "form-error", role: "alert", hidden: true});
  function fail(box, error) { if (error.name !== "AbortError" && state.user) { box.hidden = false; box.textContent = error.message; } }
  function reset() { version++; dialog?.close(); dialog?.remove(); dialog = null; panel.replaceChildren(); }
  function field(name, label, value = "", type = "text", options = null) {
    const control = options ? el("select", {name, id: `field-${name}`}, ...options.map(([key,text]) => el("option", {value:key}, text))) :
      type === "textarea" ? el("textarea", {name, id:`field-${name}`, rows:4, maxlength:4000}) :
      el("input", {name, id:`field-${name}`, type, ...(type === "password" ? {minlength:4, maxlength:1024, autocomplete:"new-password"} : {})});
    if (type === "checkbox") control.checked = !!value; else control.value = value ?? "";
    if (["username","display_name","project_number","name","password","current_password","new_password","confirm_password"].includes(name)) control.required = true;
    if (type === "text") control.maxLength = name === "project_number" ? 100 : 200;
    if (name === "current_password") { control.minLength = 1; control.autocomplete = "current-password"; }
    return el("div", {class:`management-field ${type === "checkbox" ? "check-field" : ""}`}, el("label", {for:control.id}, label), control);
  }
  function values(form) {
    const data = Object.fromEntries(new FormData(form));
    for (const box of form.querySelectorAll('input[type="checkbox"]')) data[box.name] = box.checked;
    return data;
  }
  function form(fields, label, submit, extra = []) {
    const error = errorBox();
    const form = el("form", {class:"management-form"}, ...fields, error,
      el("div", {class:"management-actions"}, el("button", {type:"submit", class:"primary"}, label), ...extra));
    form.addEventListener("submit", async event => {
      event.preventDefault(); error.hidden = true;
      const controls = [...form.querySelectorAll("input,select,textarea,button")];
      const data = values(form); const actor = state.user;
      controls.forEach(control => control.disabled = true);
      try { await submit(data, actor); }
      catch (problem) { fail(error, problem); }
      finally { controls.forEach(control => control.disabled = false); form.querySelectorAll('input[type="password"]').forEach(control => control.value = ""); }
    });
    return form;
  }
  function modal(title, fields, label, submit, note = "") {
    dialog?.close(); dialog?.remove();
    const box = el("dialog", {class:"management-dialog", "aria-labelledby":"management-dialog-title"});
    const close = () => { box.close(); box.remove(); if (dialog === box) dialog = null; };
    box.append(el("h2", {id:"management-dialog-title"}, title), note && el("p", {class:"muted"}, note),
      form(fields,label,async (data,actor) => { await submit(data); if (state.user === actor) { close(); toast("Changes saved"); await open(currentPage); } },
        [button("Cancel", close, {class:"secondary"})]));
    box.addEventListener("cancel", event => { if (box.querySelector('button[type="submit"]').disabled) event.preventDefault(); else close(); });
    document.body.append(box); dialog = box; box.showModal();
  }
  function pager(page, offset, load) {
    return el("div", {class:"pagination"}, button("← Previous", () => load(Math.max(0,offset-25)), {class:"quiet",disabled:offset===0}),
      el("span", {}, `Page ${offset/25+1}`), button("Next →", () => load(offset+25), {class:"quiet",disabled:!page.has_more}));
  }
  async function open(page, offset=0) {
    currentPage = page; const turn = ++version;
    panel.replaceChildren(el("p", {role:"status"}, "Loading…"));
    try {
      if (page === "account") { account(); return; }
      if (page === "users") {
        const data = await request(`/admin/users?limit=25&offset=${offset}`);
        if (turn !== version || !state.user) return;
        panel.replaceChildren(el("div", {class:"management-actions"}, button("Create user", createUser, {class:"primary"}), button("Refresh",()=>open(page,offset),{class:"secondary"})),
          dataTable(["Username","Display name","Role","Status","Password","Actions"], data.items.map(user => [user.username,user.display_name,user.role,user.enabled?"Enabled":"Disabled",user.must_change_password?"Change required":"Set",
            el("div",{class:"management-actions"},button("Edit",()=>editUser(user),{class:"text-button"}),user.id!==state.user.id && button("Reset password",()=>resetPassword(user),{class:"text-button"}))]),"","User accounts"), pager(data,offset,n=>open(page,n)));
      } else if (page === "project-settings") {
        const data = await request(`/management/projects?include_archived=true&limit=25&offset=${offset}`);
        if (turn !== version || !state.user) return;
        panel.replaceChildren(el("div",{class:"management-actions"},admin() && button("Create project",()=>editProject(),{class:"primary"}),button("Refresh",()=>open(page,offset),{class:"secondary"})),
          dataTable(["Project","Name","Customer","Due date","Status",""],data.items.map(project=>[project.project_number,project.name,project.customer||"—",project.due_date||"—",project.archived?"Archived":"Active",
            el("div",{class:"management-actions"},button(admin()?"Edit properties":"Details",()=>editProject(project),{class:"text-button"}),admin()&&button("Members",()=>members(project),{class:"text-button"}))]),"","Project properties"),pager(data,offset,n=>open(page,n)));
      } else if (page === "checkouts") {
        const data=await request(`/me/checkouts?limit=25&offset=${offset}`);
        if(turn!==version||!state.user)return;
        panel.replaceChildren(button("Refresh",()=>open(page,offset),{class:"secondary"}),
          data.items.length ? dataTable(["Item","Name","Revision","Acquired","Expires","Status"],data.items.map(row=>[
            button(row.item_number,()=>navigate(row.item_id,row.revision_id),{class:"text-button"}),row.item_name,`Rev ${row.revision_label}`,dateLabel(row.acquired_at),dateLabel(row.expires_at),row.status]),"","My checkouts") : el("p",{class:"muted"},"You have no unreleased checkouts for accessible items."),
          pager(data,offset,n=>open(page,n)),el("p",{class:"muted"},"Expired leases no longer permit editing. Manage checkouts through FreeCAD."));
      } else if (page === "activity") { await activity(turn); }
    } catch(error) { if(turn===version && error.name!=="AbortError" && state.user) {const box=errorBox();fail(box,error);panel.replaceChildren(box,button("Try again",()=>open(page,offset),{class:"secondary"}));} }
  }
  function createUser() {
    modal("Create user",[field("username","Username"),field("display_name","Display name"),field("role","Role","user","text",[["user","User"],["admin","Administrator"]]),field("password","Temporary password","","password")],"Create user",data=>request("/admin/users",{method:"POST",body:data}),"Provide the temporary password to the user securely. They must change it at first sign-in.");
  }
  function editUser(user) {
    modal(`Edit ${user.username}`,[field("display_name","Display name",user.display_name),field("role","Role",user.role,"text",[["user","User"],["admin","Administrator"]]),field("enabled","Account enabled",user.enabled,"checkbox")],"Save user",data=>request(`/admin/users/${user.id}`,{method:"PUT",body:data}),"Disabling an account or changing its role revokes its sessions.");
  }
  function resetPassword(user) {
    modal(`Reset password · ${user.username}`,[field("password","Temporary password","","password")],"Reset password",data=>request(`/admin/users/${user.id}/reset-password`,{method:"POST",body:data}),"All sessions will be revoked. The user must change this temporary password before accessing data.");
  }
  function editProject(project=null) {
    const fields=[field("project_number","Project number",project?.project_number),field("name","Name",project?.name),field("customer","Customer",project?.customer),field("due_date","Due date",project?.due_date,"date"),field("description","Description",project?.description,"textarea"),field("archived","Archived",project?.archived,"checkbox")];
    if(!admin()) { modal(project.project_number,fields,"Close",async()=>{});dialog.querySelectorAll("input,textarea,select").forEach(control=>control.disabled=true);return; }
    modal(project?`Edit ${project.project_number}`:"Create project",fields,"Save project",async data=>{
      data.due_date ||= null;
      await request(`/management/projects${project?`/${project.id}`:""}`,{method:project?"PUT":"POST",body:data});await loadProjects();
    },"Archiving retains project data and membership; it removes the project from active catalog selectors.");
  }
  async function members(project) {
    const turn=version;
    try {
      const [members,users]=await Promise.all([request(`/management/projects/${project.id}/members`),api.allPages("/admin/users",ctx.signal())]);
      if(turn!==version||!state.user)return;
      const options=users.map(user=>[user.id,`${user.username}${user.enabled?"":" (disabled)"}`]);
      modal(`Members · ${project.project_number}`,[field("user_id","User",options[0]?.[0],"text",options),field("role","Project role","viewer","text",[["viewer","Viewer"],["editor","Editor"],["owner","Owner"]])],"Set membership",data=>request(`/management/projects/${project.id}/members/${data.user_id}`,{method:"PUT",body:{role:data.role}}),"Setting membership adds a user or replaces their current project role.");
      dialog.insertBefore(dataTable(["User","Role",""],members.map(member=>[member.username,member.role,button("Remove",()=>{
        modal(`Remove ${member.username}?`,[],"Remove membership",()=>request(`/management/projects/${project.id}/members/${member.id}`,{method:"DELETE"}),`Remove access through ${project.project_number}. Access through other projects remains.`);
      },{class:"text-button"})]),"","Project members"),dialog.querySelector("form"));
    } catch(error) {if(error.name!=="AbortError")toast(error.message);}
  }
  function account() {
    panel.replaceChildren(el("h2",{},state.user.must_change_password?"Change your temporary password":"Change password"),
      el("p",{class:"muted"},state.user.must_change_password?"Choose a new password before accessing the workspace.":"Changing your password signs out all sessions, including this one."),
      form([field("current_password","Current password","","password"),field("new_password","New password","","password"),field("confirm_password","Confirm new password","","password")],"Change password",async data=>{
        if(data.new_password!==data.confirm_password)throw new Error("New passwords do not match.");
        await request("/auth/password",{method:"POST",body:{current_password:data.current_password,new_password:data.new_password}});
        resetSession("Password changed. Sign in with your new password.");
      }));
  }
  async function activity(turn) {
    const filters=form([field("q","Search action, item or username"),field("project_id","Project","","text",[["","All accessible projects"],...state.projects.map(p=>[p.id,`${p.project_number} · ${p.name}`])]),field("action","Exact action (optional)"),field("actor_id","User","","text",[["","All accessible users"]]),field("start","From","","date"),field("end","Through","","date")],"Filter",data=>load(data,0));
    const results=el("div",{class:"activity-results"});panel.replaceChildren(filters,results);
    const actors=await api.allPages("/activity/actors",ctx.signal());
    if(turn!==version||!state.user)return;
    const actorPicker=filters.querySelector('[name="actor_id"]');
    actorPicker.replaceChildren(el("option",{value:""},"All accessible users"),...actors.map(user=>el("option",{value:user.id},user.username)));
    async function load(data,offset){
      const params=new URLSearchParams({limit:"25",offset:String(offset)});for(const [key,value]of Object.entries(data))if(value)params.set(key,value);
      const page=await request(`/activity?${params}`);
      if(turn!==version||!state.user)return;
      results.replaceChildren(page.items.length?dataTable(["When","User","Action","Subject","Details"],page.items.map(row=>[dateLabel(row.occurred_at),row.username,row.event_type,row.item_id?button(row.subject,()=>navigate(row.item_id,row.revision_id||undefined),{class:"text-button"}):row.subject,
        row.details?el("details",{},el("summary",{},"Details"),el("pre",{class:"audit-details"},JSON.stringify(row.details,null,2))):"—"]),"","Activity history"):el("p",{class:"muted"},"No matching activity."),pager(page,offset,n=>load(data,n).catch(error=>toast(error.message))));
    }
    await load({},0);
  }
  return {open,reset};
}
