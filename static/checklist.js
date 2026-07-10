(() => {
  const key = "osf-project-checklist-state-v2";
  const nodes = [...document.querySelectorAll(".node")];
  const checks = [...document.querySelectorAll(".node-check")];
  const rows = JSON.parse(document.getElementById("rows-data").textContent);
  let state = {};
  try { state = JSON.parse(localStorage.getItem(key) || "{}"); } catch (_) {}

  function ownCheck(node){ return node.querySelector(":scope > .node-row > .node-check"); }
  function paint(check){ check.closest(".node").classList.toggle("checked", check.checked); }
  function save(){ const s={}; checks.forEach(c=>{if(c.checked)s[c.closest(".node").dataset.guid]=true}); localStorage.setItem(key,JSON.stringify(s)); }
  function progress(){ const n=checks.filter(c=>c.checked).length; document.getElementById("progressText").textContent=`${n} of ${checks.length} checked`; document.getElementById("progressFill").style.width=`${checks.length?n/checks.length*100:0}%`; }
  checks.forEach(c=>{c.checked=!!state[c.closest(".node").dataset.guid];paint(c);c.addEventListener("change",()=>{paint(c);save();progress();filter()})});

  document.addEventListener("click",e=>{const t=e.target.closest(".toggle");if(t)t.closest(".node").classList.toggle("collapsed")});
  document.getElementById("expand").onclick=()=>nodes.forEach(n=>n.classList.remove("collapsed"));
  document.getElementById("collapse").onclick=()=>nodes.forEach(n=>{if(n.querySelector(":scope > .children"))n.classList.add("collapsed")});
  document.getElementById("clear").onclick=()=>{if(confirm("Clear every checkbox?")){checks.forEach(c=>{c.checked=false;paint(c)});save();progress();filter()}};

  const search=document.getElementById("search"), visibility=document.getElementById("visibility"), completion=document.getElementById("completion");
  function filter(){
    const q=search.value.trim().toLowerCase();
    function evalNode(node){
      const childList=node.querySelector(":scope > .children");
      const childVisible=childList?[...childList.children].map(evalNode).some(Boolean):false;
      const c=ownCheck(node), own=(!q||node.dataset.search.includes(q))&&(visibility.value==="all"||visibility.value===(node.dataset.public==="true"?"public":"private"))&&(completion.value==="all"||completion.value===(c.checked?"checked":"unchecked"));
      node.classList.toggle("hidden",!(own||childVisible));
      if(childVisible&&q)node.classList.remove("collapsed");
      return own||childVisible;
    }
    document.querySelectorAll(".tree").forEach(tree=>[...tree.children].forEach(evalNode));
  }
  [search,visibility,completion].forEach(x=>x.addEventListener(x===search?"input":"change",filter));

  function csv(v){v=String(v??"");return /[",\n]/.test(v)?`"${v.replaceAll('"','""')}"`:v}
  document.getElementById("export").onclick=()=>{
    const out=[["guid","title","url","visibility","depth","parent_guid","checked"]];
    rows.forEach(r=>out.push([r.guid,r.title,r.url,r.public?"Public":"Private",r.depth,r.parent_guid,state[r.guid]?"Yes":"No"]));
    const blob=new Blob([out.map(row=>row.map(csv).join(",")).join("\n")],{type:"text/csv"});
    const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="osf_project_checklist.csv";a.click();URL.revokeObjectURL(a.href);
  };
  progress();filter();
})();
