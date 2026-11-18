(() => {
  const area = document.querySelector("#workspace");
  if (!area) return;
  const notice = document.querySelector("#feedback");
  const chosen = new Set();
  let busy = false, active, debounce;
  function selection() {
    const boxes = [...area.querySelectorAll(".pick")];
    for (const box of boxes) box.checked = chosen.has(box.value);
    const all = area.querySelector("#all");
    if (!all) return;
    all.checked = boxes.length > 0 && boxes.every(b => b.checked);
    all.indeterminate = boxes.some(b => b.checked) && !all.checked;
    area.querySelector("#count").textContent = "已选 " + chosen.size + " 人";
    area.querySelector("#ids").value = [...chosen].join(",");
  }
  async function refresh(url = location.href, navigate = false, quiet = false, fresh = false) {
    const draft = area.querySelector('.actionbar input[name="label"]');
    if (busy || (quiet && (draft?.value || area.querySelector("#batch select")?.value)) || (quiet && (active || document.hidden || area.querySelector(".drawer") || area.contains(document.activeElement) && document.activeElement.matches("input:not([type=checkbox]),select")))) return;
    active?.abort();
    const request = new AbortController();
    active = request;
    try {
      const res = await fetch(url, {signal:request.signal, cache:"no-store", headers:{"X-Wgvps-View": quiet || fresh ? "fresh" : "browse"}});
      if (!res.ok) throw Error("刷新失败，请检查连接或重新登录");
      const doc = new DOMParser().parseFromString(await res.text(), "text/html");
      const content = doc.querySelector("#workspace");
      if (!content) throw Error("读取管理页面失败");
      const input = document.activeElement;
      const caret = input.name === "q" ? input.selectionStart : null;
      area.replaceChildren(...content.childNodes);
      if (navigate) history.pushState(null,"",url);
      if (caret !== null) {
        const search = area.querySelector("input[name=q]");
        search?.focus(); search?.setSelectionRange(caret,caret);
      }
      selection();
      if (notice.dataset.error) {notice.textContent="";delete notice.dataset.error;}
    } catch(e) {
      if (e.name !== "AbortError") { notice.textContent=e.message; notice.dataset.error="1"; }
    } finally { if (active===request) active=null; }
  }
  function search(form, manual = false) {
    const params = new URLSearchParams(new FormData(form));
    if (!manual) { chosen.clear(); params.delete("page"); }
    refresh(form.action+"?"+params,true,false,manual);
  }
  area.addEventListener("click", e => {
    const link=e.target.closest("a[data-view]");
    if (link && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
      e.preventDefault(); clearTimeout(debounce); refresh(link.href,true);
    }
  });
  area.addEventListener("change", e => {
    const item=e.target;
    if(item.id==="all") for(const b of area.querySelectorAll(".pick")) {
      if(item.checked) chosen.add(b.value); else chosen.delete(b.value);
    }
    if(item.matches(".pick")) {if(item.checked) chosen.add(item.value); else chosen.delete(item.value);}
    if(item.closest(".filters") && item.matches("select")) search(item.form);
    selection();
  });
  area.addEventListener("input", e => {
    if(e.target.name==="q") {active?.abort(); clearTimeout(debounce); const form=e.target.form; debounce=setTimeout(()=>search(form),300);}
  });
  area.addEventListener("submit", async e => {
    const form=e.target, action=e.submitter?.value;
    clearTimeout(debounce);
    if(form.matches(".filters")) {e.preventDefault();search(form,true);return;}
    if(busy) {e.preventDefault();return;}
    if(form.id==="batch" && !chosen.size) {e.preventDefault();notice.textContent="请先选择客户";return;}
    if(["batch-disable","disable","group-delete"].includes(action) && !confirm("确认执行 "+e.submitter.textContent+"？"+(form.id==="batch"?" 已选 "+chosen.size+" 人":""))) {e.preventDefault();return;}
    if(["issue","bundle","archive","confirm-delete","confirm-rotate"].includes(action)) return;
    e.preventDefault();
    busy=true;active?.abort();
    notice.textContent="正在执行…";
    const fields=new URLSearchParams(new FormData(form));fields.set("action",action);
    let next=location.href;
    try {
      const res=await fetch("/admin",{method:"POST",body:fields});
      if(res.ok && res.headers.get("content-type")==="application/zip") {
        const file=URL.createObjectURL(await res.blob());
        const a=document.createElement("a");a.href=file;a.download="wireguard-selected.zip";a.click();
        setTimeout(()=>URL.revokeObjectURL(file),60000);
        notice.textContent="已生成所选客户配置 ZIP";
      } else {
        const doc=new DOMParser().parseFromString(await res.text(),"text/html");
        notice.textContent=[doc.querySelector("h1")?.textContent,doc.querySelector(".result,main p:not(:has(a))")?.textContent].filter(Boolean).join(" · ") || "操作未完成";
        const created=doc.querySelector("[data-created]")?.dataset.created;
        if(created) next="/admin?customer="+encodeURIComponent(created);
        if(!res.ok) return;
      }
      chosen.clear();
    } catch {notice.textContent="请求中断，请刷新核对结果后再操作";return;}
    finally {busy=false;}
    await refresh(next,next!==location.href,false,true);
  });
  window.addEventListener("popstate",()=>refresh());
  if(["/admin","/admin/status"].includes(location.pathname))
    setInterval(()=>refresh(location.href,false,true),30000);
})();
