"use strict";

function savedJSON(key){try{return JSON.parse(localStorage.getItem(key)||"null");}catch{return null;}}
function retryKey(){return `pcb-retry-${state.project.id}`;}
function getRetry(){return state.project?savedJSON(retryKey()):null;}
function nextStep(){
 const p=state.project;
 if(!state.gates[0]?.approved)return {index:0,title:"กำหนดโจทย์ให้พร้อม",detail:"ตรวจข้อเสนอจากบรีฟ เลือกค่าที่ต้องการ แล้วอนุมัติ Requirements",page:"requirements"};
 if(!p.discovery&&state.settings.mode==="codex")return {index:1,title:"ให้ AI หาชุดอุปกรณ์",detail:"ค้นรุ่นจริงและลิงก์ผู้ผลิต แล้วให้คุณเลือกก่อนอ่านเอกสาร",stage:"discover"};
 if(p.discovery?.parts.some(p=>p.status!=="selected"))return {index:1,title:"เลือกชุดอุปกรณ์",detail:"ตรวจรายการที่แนะนำ เลือกทั้งชุดหรือเปลี่ยนเฉพาะรุ่นที่ต้องการ",page:"research"};
 if(!p.circuit)return {index:2,title:p.research?"สร้างร่างจากหลักฐานที่มี":"อ่านเอกสารและสร้างร่าง",detail:p.research?"ใช้ผล Research ที่เก็บไว้ เพื่อลดการทำงานซ้ำ":"ดาวน์โหลด PDF อ่านหลักฐาน แล้วสร้าง BOM และตารางการเชื่อมต่อ",stage:p.research?"circuit":"plan"};
 if(!state.gates.find(g=>g.gate==="connections")?.approved)return {index:3,title:"ตรวจร่างวงจรและขาที่ยังขาด",detail:"มีร่างแล้ว ตรวจ BOM, Pin-to-pin และหลักฐานก่อนอนุมัติ ขั้นนี้ไม่เรียก AI เพิ่ม",page:"circuit"};
 return {index:4,title:"ทำแบบใน EasyEDA แล้วนำกลับมาตรวจ",detail:"ส่งออกข้อมูลอ้างอิง แล้วนำ schematic / PCB ที่คุณทำกลับเข้ามาเพื่อตรวจขั้นถัดไป",page:"files"};
}
function journey(){
 const next=nextStep(), steps=[["โจทย์","requirements"],["อุปกรณ์","research"],["หลักฐาน","research"],["ตรวจร่าง","circuit"],["แบบ PCB","files"]];
 const retry=getRetry();
 const pending=savedJSON("pcb-active-job");
 if(pending?.project_id===state.project.id&&!state.job)return `<div class="resume-card"><div><strong>มีงานที่เริ่มไว้แล้ว</strong><p>เชื่อมต่อกลับเพื่อดูสถานะหรือหยุดงาน โดยไม่เรียก AI ซ้ำ</p></div><button data-action="reconnect-job">กลับไปดูงาน</button></div>`;
 return `<div class="journey" aria-label="ขั้นตอนงาน">${steps.map(([name,page],i)=>`<button data-action="nav" data-page="${page}" class="journey-step ${i===next.index?"current":""}" ${i===next.index?'aria-current="step"':""}><span>${i+1}</span>${name}</button>`).join("")}</div>${retry?`<div class="resume-card"><div><strong>งานก่อนหน้าหยุดอยู่</strong><p>ทำขั้นที่ค้างต่อได้ โดยใช้ผลที่บันทึกไว้ ขั้น AI ที่ยังไม่เสร็จจะเริ่มเรียกใหม่</p></div><button class="primary" data-action="resume-job">ทำต่อจากขั้นที่ค้าง →</button></div>`:""}`;
}
async function continueProject(){const n=nextStep();return n.stage?runStage(n.stage):work(()=>navigate(n.page),"");}

renderOverview=function(){
 const p=state.project,n=nextStep(), selected=p.discovery?.parts.filter(x=>x.status==="selected").length||0;
 const facts=p.research?.facts||[], confirmed=facts.filter(f=>f.status==="Confirmed").length;
 return `<div class="card lab-hero"><div class="lab-copy"><span class="eyebrow">YOUR PERSONAL PCB LAB · V${p.version}</span><h2>${esc(n.title)}</h2><p>${esc(n.detail)}</p><button class="primary continue-button" data-action="continue">ทำต่อ →</button><small>โมเดล ${esc(state.settings.model||"Offline")} · effort ${esc(state.settings.effort||"ค่าเริ่มต้น")}</small></div><div class="board-art" aria-hidden="true"><i class="trace t1"></i><i class="trace t2"></i><i class="trace t3"></i><span class="chip">PCB<br><b>LAB</b></span><span class="pad p1"></span><span class="pad p2"></span><span class="pad p3"></span><span class="board-caption">BUILD · CHECK · ITERATE</span></div></div>
 <div class="lab-stats"><div><span>อุปกรณ์ที่เลือก</span><strong>${selected}<small> / ${p.discovery?.parts.length||0}</small></strong></div><div><span>เอกสารที่เก็บไว้</span><strong>${p.sources.length}</strong></div><div><span>หลักฐานที่คุณยืนยัน</span><strong>${confirmed}<small> / ${facts.length}</small></strong></div></div>
 ${p.circuit?card("ร่างพร้อมให้ตรวจ","มีผลลัพธ์แล้ว เปิดดูได้ทันทีโดยไม่ใช้โทเคนเพิ่ม",`<div class="actions"><button data-action="nav" data-page="circuit">เปิด BOM / Pin-to-pin →</button><button data-action="nav" data-page="review">ดูประเด็นที่ต้องแก้</button></div>`):""}
 <details class="fold"><summary>บรีฟและสถานะงานล่าสุด</summary><p class="brief-text">${esc(p.brief)}</p><pre>${esc(p.pipeline_status||"พร้อมเริ่มงาน")}</pre></details>
 <details class="fold"><summary>การใช้ AI · โทเคน เวลา และค่าใช้จ่าย</summary>${usageSummary()}</details>
 <details class="fold"><summary>เส้นทางการตรวจและอนุมัติทั้งหมด</summary>${gateCards()}</details>`;
};

function foldElement(element,label,open=false){
 const fold=document.createElement("details");fold.className="fold";fold.open=open;
 const summary=document.createElement("summary");summary.textContent=label;
 element.replaceWith(fold);fold.append(summary,element);
}
function simplifyPage(){
 const p=state.project;if(!p)return;
 if(state.page==="circuit"&&p.circuit){
  const cards=[...$("#content").children].filter(e=>e.classList.contains("card"));
  const views=[["bom","รายการอุปกรณ์ (BOM)"],["connections","Pin-to-pin"],["pins","Pin assignment"]];
  const selected=state.circuitView||"bom";
  cards[0]?.insertAdjacentHTML("beforeend",`<div class="view-switch" aria-label="มุมมองร่างวงจร">${views.map(([key,label])=>`<button data-action="circuit-view" data-view="${key}" aria-pressed="${selected===key}" class="${selected===key?"selected":""}">${label}</button>`).join("")}</div><div class="actions"><button data-action="nav" data-page="research">ตรวจ / เติมหลักฐาน</button><button data-action="nav" data-page="review">ดูประเด็นและการอนุมัติ →</button></div>`);
  views.forEach(([key],i)=>{if(cards[i+1])cards[i+1].hidden=key!==selected;});
  cards.slice(4).forEach(el=>foldElement(el,el.querySelector("h2")?.textContent||"รายละเอียด"));
  [...$("#content").querySelectorAll(":scope > .grid")].forEach(el=>foldElement(el,"Decoupling และข้อจำกัดการออกแบบ"));
 }
 if(state.page==="research"){
  const partsButton=$("[data-action='parts-all']");
  if(partsButton&&p.discovery?.parts.every(x=>x.status==="selected")){partsButton.disabled=true;partsButton.textContent="เลือกทั้งชุดแล้ว ✓";}
  const cards=[...$("#content").children].filter(e=>e.classList.contains("card"));
  if(p.discovery&&cards[0]){
   const parts=[...cards[0].querySelectorAll(":scope > .source-fact")];
   if(parts.length){const group=document.createElement("div");parts[0].before(group);parts.forEach(el=>group.append(el));foldElement(group,`ดู / เปลี่ยนอุปกรณ์ ${parts.length} รายการ`,p.discovery.parts.some(x=>x.status!=="selected"));}
   const status=cards[0].querySelector(".notice");if(status)foldElement(status,"รายละเอียดการทำงาน / เอกสารที่ยังขาด");
   const unresolved=cards[0].querySelector(":scope > ul");if(unresolved)foldElement(unresolved,"ข้อควรตรวจของชุดอุปกรณ์");
   if(p.circuit)cards[0].insertAdjacentHTML("beforeend",'<div class="actions"><button class="primary" data-action="nav" data-page="circuit">ดูร่างวงจรที่สร้างไว้ →</button></div>');
  }
  if(cards[1])foldElement(cards[1],`เอกสารต้นฉบับ (${p.sources.length}) · เพิ่ม PDF เองได้`);
  if(cards[2]){
   [...cards[2].querySelectorAll(":scope > .source-fact")].forEach(el=>foldElement(el,`${el.querySelector("strong")?.textContent||"หลักฐาน"} · ${(el.querySelector("p")?.textContent||"").slice(0,75)}`));
   foldElement(cards[2],`ตรวจและยืนยันหลักฐาน (${p.research?.facts.length||0})`,!!p.research);
  }
  if(cards[0])cards[0].insertAdjacentHTML("beforeend",'<div class="actions"><button data-action="retry-docs">ลองดาวน์โหลดเอกสารที่ขาดอีกครั้ง</button><button data-action="nav" data-page="files">นำเข้า PDF เอง</button></div>');
 }
 if(state.page==="requirements"){
  const cards=[...$("#content").children].filter(e=>e.classList.contains("card"));
  if(cards[3])foldElement(cards[3],"ดู Block diagram และ Power tree");
  if(state.gates[0]?.approved)$("#content").insertAdjacentHTML("afterbegin",'<div class="resume-card"><div><strong>โจทย์อนุมัติแล้ว ✓</strong><p>พร้อมไปขั้นตอนถัดไปของโปรเจกต์</p></div><button class="primary" data-action="continue">ทำต่อ →</button></div>');
 }
}

async function stopJob(){
 if(!state.job)return;
 const button=$("#stop-job");button.disabled=true;button.textContent="กำลังหยุด…";
 try{await api(`/api/jobs/${state.job.id}/cancel`,"POST");state.busyLabel="กำลังหยุด · เก็บผลขั้นตอนที่สำเร็จ";}
 catch(error){button.disabled=false;button.textContent="ลองหยุดอีกครั้ง";message(error.message,true);}
}
async function followJob(job){
 state.job=job;const button=$("#stop-job");button.classList.remove("hidden");button.disabled=false;button.textContent="หยุดงาน";
 render();
 try{
  for(;;){
   const status=await api(`/api/jobs/${job.id}`);state.busyLabel=status.progress||"กำลังทำงาน";
   if(["done","error","cancelled"].includes(status.status)){
    localStorage.removeItem("pcb-active-job");
    if(status.status==="done"){
     adopt(status.result);localStorage.removeItem(retryKey());
     state.page=job.stage==="requirements"?"requirements":job.stage==="discover"?"research":job.stage==="review"?"review":state.project.circuit?"circuit":"research";
     await refreshList();render();message("เสร็จแล้ว — เปิดผลลัพธ์ของขั้นตอนนี้ให้แล้ว");return;
    }
    await loadProject(job.project_id);
    localStorage.setItem(retryKey(),JSON.stringify({stage:job.stage,extra:job.extra||{}}));render();
    message(status.error||"งานหยุดแล้ว ผลก่อนหน้ายังอยู่",status.status==="error");return;
   }
   await new Promise(resolve=>setTimeout(resolve,1000));
  }
 }catch(error){state.job=null;render();throw error;}finally{state.job=null;button.classList.add("hidden");}
}
async function reconnectJob(){
 try{
  const active=await api("/api/jobs"),saved=savedJSON("pcb-active-job");
  const job=active[0]?(active[0].id===saved?.id?saved:active[0]):saved;
  if(!job)return;
  await work(async()=>{
   await loadProject(job.project_id);
   try{await followJob(job);}catch(error){
    if(error.status!==404)throw error;
    // Server restart loses in-memory jobs. Keep a manual retry, never auto-call AI.
    localStorage.removeItem("pcb-active-job");localStorage.setItem(retryKey(),JSON.stringify({stage:job.stage,extra:job.extra||{}}));render();throw error;
   }
  },"");
 }catch(error){message(error.message,true);}
}
