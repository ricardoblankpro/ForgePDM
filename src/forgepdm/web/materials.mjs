// Simple catalog descriptions and revision-bound material selection.
export function materialsUI({api, el, button: makeButton, state, descriptionSaved}) {
  const button=(label,action)=>makeButton(label,action,{class:"secondary"});
  const error=(host,e)=>host.append(el("p",{role:"alert"},e.message));
  function field(label,value="") {
    const input=el("input",{value,maxlength:"1000"});
    return {input,node:el("label",{},label,input)};
  }
  async function render(host,item,revision) {
    host.classList.add("material-panel");
    try {
      if(item.number.startsWith("S")) {
        const path=`/revisions/${revision.id}/reference-mass`;
        const mass=await api.request(path);
        if(!host.isConnected)return;
        host.replaceChildren(el("h3",{},"Supplier reference mass"),el("p",{},mass.mass_kg!=null?`${Number(mass.mass_kg)*1000} g per piece`:`Mass unavailable: ${mass.reason}`));
        if(mass.mass_kg!=null)host.append(el("p",{},`${mass.supplier} · ${mass.source_article} · retrieved ${mass.retrieved_at.slice(0,10)}`),el("a",{href:mass.source_url,target:"_blank",rel:"noopener noreferrer"},"Supplier source"));
        if(mass.mass_kg==null && revision.lifecycle_state==="working") {
          const checkout=await api.request(`/revisions/${revision.id}/checkout`);
          if(checkout?.user_id===state.user?.id)host.append(button("Find reference mass",async()=>{try{await api.request(path+"/lookup",{method:"POST",body:{}});await render(host,item,revision);}catch(e){error(host,e);}}));
          else host.append(el("p",{},"Acquire a Working checkout to save reference mass."));
        }
        if(state.user?.role==="admin") {
          const upload=el("input",{type:"file",accept:".csv,text/csv"});
          host.append(el("label",{},"Import supplier reference CSV",upload));
          upload.addEventListener("change",async()=>{try{const file=upload.files[0];if(!file)return;if(file.size>1024*1024)throw new Error("CSV must be at most 1 MiB");const result=await api.request("/reference-masses/import",{method:"POST",body:{csv_text:await file.text()}});host.append(el("p",{},`Imported ${result.imported} reference records. Use Find reference mass on a checked-out S revision to adopt one.`));}catch(e){error(host,e);}});
        }
        return;
      }
      const path=`/revisions/${revision.id}/description`;
      const [current,checkout]=await Promise.all([api.request(path),api.request(`/revisions/${revision.id}/checkout`)]);
      if(!host.isConnected)return;
      const series=item.number[0];
      const editable=revision.lifecycle_state==="working"&&checkout?.user_id===state.user?.id;
      host.replaceChildren(el("h3",{},series==="P"?"Raw material":"Description"),el("p",{},current.description||"No description assigned."));
      if(current.physical_material)host.append(el("p",{},`Physical material: ${current.physical_material.name} · ${current.physical_material.density_kg_m3} kg/m³`));
      if(series==="P"){
        const mass=await api.request(`/revisions/${revision.id}/mass`);
        host.append(el("p",{},mass.mass_kg!=null?`Uploaded mass: ${Number(mass.mass_kg).toPrecision(8)} kg`:`Mass unavailable: ${mass.reason}`));
      }
      if(series==="M"&&!current.physical_material)host.append(el("p",{},"For automatic part mass, use Link Physical Material in FreeCAD."));
      if(!["P","A","M"].includes(series))return;
      if(!editable) {
        host.append(el("p",{},revision.lifecycle_state==="working"?"Acquire a checkout to edit.":"Create a new revision to change this description."));
        if(revision.lifecycle_state==="working")host.append(button("Acquire checkout",async()=>{try{await api.request(`/revisions/${revision.id}/checkout`,{method:"POST"});await render(host,item,revision);}catch(e){error(host,e);}}));
        if(revision.lifecycle_state==="released")host.append(button("Create new revision",async()=>{const note=window.prompt("Revision change note");if(!note)return;try{const r=await api.request(`/items/${item.id}/revisions`,{method:"POST",body:{change_note:note}});location.hash=new URLSearchParams({item:item.id,revision:r.id}).toString();}catch(e){error(host,e);}}));
        return;
      }
      async function save(description,material_revision_id=null) {
        try{const saved=await api.request(path,{method:"PUT",body:{description,material_revision_id,expected_token:current.token}});descriptionSaved?.(revision,saved);await render(host,item,revision);}catch(e){error(host,e);}
      }
      if(series==="P") {
        const query=field("Find raw material");
        const results=el("div");
        host.append(query.node,button("Search materials",async()=>{
          try {
            const page=await api.request(`/items?number_series=M&q=${encodeURIComponent(query.input.value)}&limit=100`);
            results.replaceChildren(...page.items.filter(r=>r.lifecycle_state!=="obsolete").map(r=>button(`${r.number} — ${r.description||r.name}`,async()=>{
              try{const selected=await api.request(`/revisions/${r.current_revision_id}/description`);await save(selected.description,r.current_revision_id);}catch(e){error(host,e);}
            })));
            if(!page.items.length)results.append(el("p",{},"No matching materials. Register one in the catalog."));
            if(page.has_more)results.append(el("p",{},"Refine the search to see more materials."));
          }catch(e){error(host,e);}
        }),results,button("Clear material",()=>save("")));
      } else {
        const description=field(series==="A"?"Assembly description":"Material description",current.description);
        host.append(description.node,button("Save description",()=>save(description.input.value)));
      }
      host.append(button("Check in",async()=>{try{await api.request(`/revisions/${revision.id}/checkin`,{method:"POST",body:{}});await render(host,item,revision);}catch(e){error(host,e);}}));
    }catch(e){error(host,e);}
  }
  function create(host,navigate) {
    host.classList.add("material-panel");
    const description=field("Material description");
    host.replaceChildren(el("h3",{},"Register raw material"),description.node,button("Register material",async()=>{
      const text=description.input.value.trim();
      if(!text){error(host,new Error("Enter a material description."));return;}
      try {
        const item=await api.request("/items",{method:"POST",body:{kind:"part",number_series:"M",name:text.slice(0,200),description:text}});
        navigate(item);
      }catch(e){error(host,e);}
    }));
  }
  return {render,create};
}
