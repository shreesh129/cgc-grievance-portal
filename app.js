"use strict";
const API=(new URLSearchParams(location.search).get("api")||localStorage.getItem("GRIEVANCE_API")||"http://127.0.0.1:8000").replace(/\/$/,"");
const $=id=>document.getElementById(id);
let token=null,session=null,rec=null,chunks=[],voice=null,lastComplaint=null;

function esc(v){return String(v??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]))}
function setOut(v){$("out").textContent=typeof v==="string"?v:JSON.stringify(v,null,2)}
async function request(path,options={}){
  const headers=new Headers(options.headers||{});
  if(token)headers.set("Authorization","Bearer "+token);
  const r=await fetch(API+path,{...options,headers});
  let j={};try{j=await r.json()}catch{}
  if(!r.ok)throw Error(typeof j.detail==="string"?j.detail:(j.detail?.message||"Request failed"));
  return j;
}
function loggedIn(){return !!token}
function renderSession(){
  $("sessionState").textContent=session?`Authenticated as ${session.role} (${session.login_id})`:"Not authenticated";
  $("logout").disabled=!session;
  $("complaintSection").hidden=!session||!["student","teacher"].includes(session.role);
  $("authoritySection").hidden=!session||!["mentor","administration","hod","dean","managing_director","vice_chancellor"].includes(session.role);
}
$("login").onclick=async()=>{
 try{
  const j=await request("/api/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({login_id:$("id").value,password:$("password").value,portal:$("portal").value})});
  token=j.access_token;session=j;renderSession();setOut(j);if(["mentor","administration","hod","dean","managing_director","vice_chancellor"].includes(j.role))refreshDashboard();
 }catch(e){setOut(e.message)}
};
$("logout").onclick=async()=>{try{await request("/api/logout",{method:"POST"})}catch{} token=null;session=null;renderSession();setOut("Logged out.")};
$("record").onclick=async()=>{
 try{
  if(!navigator.mediaDevices?.getUserMedia)throw Error("Audio recording is not supported by this browser.");
  const stream=await navigator.mediaDevices.getUserMedia({audio:true});
  rec=new MediaRecorder(stream);chunks=[];rec.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};
  rec.onstop=()=>{voice=new Blob(chunks,{type:rec.mimeType||"audio/webm"});stream.getTracks().forEach(t=>t.stop());$("voiceState").textContent="Voice recorded and ready.";};
  rec.start();$("record").disabled=true;$("stop").disabled=false;$("voiceState").textContent="Recording...";
 }catch(e){$("voiceState").textContent=e.message}
};
$("stop").onclick=()=>{if(rec&&rec.state!=="inactive")rec.stop();$("record").disabled=false;$("stop").disabled=true};
$("submit").onclick=async()=>{
 try{
  if(!session||!["student","teacher"].includes(session.role))throw Error("Login as a student or teacher first.");
  const data={role:session.role,user_id:session.login_id,user_name:session.name,anonymous:$("anon").checked,
   portal:$("complaintPortal").value,category:$("category").value,sub_category:$("sub").value,description:$("desc").value,
   gender:$("gender").value||null,hostel:$("hostel").value||null,block_no:$("block").value||null,
   class_no:$("class").value||null,lab_no:$("lab").value||null,staffroom:$("staffroom").value||null,target_authority:$("authority").value||null};
  let r;
  if(voice){const fd=new FormData();fd.append("payload",JSON.stringify(data));fd.append("voice",voice,"complaint.webm");r=await request("/api/complaints/with-voice",{method:"POST",body:fd})}
  else r=await request("/api/complaints",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});
  voice=null;$("voiceState").textContent="";$("track").value=r.tracking_id;setOut(r);await trackComplaint();
 }catch(e){setOut(e.message)}
};
async function trackComplaint(){
 try{
  if(!token)throw Error("Login first.");
  const r=await request("/api/complaints/"+encodeURIComponent($("track").value.trim()));lastComplaint=r;
  $("trackOut").innerHTML=`<p><b>${esc(r.tracking_id)}</b> | ${esc(r.status)} | ${esc(r.priority)} | Assigned: ${esc(r.assigned_to)}</p>
  <p><b>Category:</b> ${esc(r.category)} / ${esc(r.sub_category)}</p><p><b>Description:</b> ${esc(r.description)}</p>
  <p><b>Submitted:</b> ${esc(r.submitted_at)} | <b>Escalation level:</b> ${esc(r.escalation_level)}</p>
  <h3>Timeline</h3><ol>${(r.events||[]).map(e=>`<li>${esc(e.created_at)} — <b>${esc(e.event_type)}</b> ${esc(e.note||"")}</li>`).join("")}</ol>
  ${r.voice_available?`<audio controls id="voicePlayer"></audio>`:""}`;
  $("actions").hidden=!(session&&session.login_id===r.user_id);
  if(r.voice_available){
   const audio=$("voicePlayer");
   if(audio){const rr=await fetch(API+"/api/complaints/"+encodeURIComponent(r.tracking_id)+"/voice",{headers:{Authorization:"Bearer "+token}});if(rr.ok){audio.src=URL.createObjectURL(await rr.blob());}}
  }
 }catch(e){$("trackOut").textContent=e.message;$("actions").hidden=true}
}
$("trackBtn").onclick=trackComplaint;
$("readdress").onclick=async()=>{
 try{if(!lastComplaint)throw Error("Track a complaint first.");const r=await request("/api/complaints/"+lastComplaint.tracking_id+"/readdressal",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({reason:$("readdressReason").value})});setOut(r);await trackComplaint()}catch(e){setOut(e.message)}
};
$("feedback").onclick=async()=>{
 try{if(!lastComplaint)throw Error("Track a complaint first.");const r=await request("/api/complaints/"+lastComplaint.tracking_id+"/feedback",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({rating:Number($("rating").value),comment:$("feedbackComment").value||null})});setOut(r);await trackComplaint()}catch(e){setOut(e.message)}
};
async function refreshDashboard(){
 try{
  const d=await request("/api/admin/dashboard");$("dash").innerHTML=`<p>Total: <b>${d.total}</b> | Open: <b>${d.open}</b> | High: <b>${d.high}</b> | Medium: <b>${d.medium}</b> | Low: <b>${d.low}</b> | Last 45 min: <b>${d.complaints_last_45_minutes}</b> | Surge: <b>${d.surge_trigger_50_in_45m?"ACTIVE":"inactive"}</b></p>`;
  const list=await request("/api/complaints?limit=50");$("queue").innerHTML=list.length?list.map(c=>`<div><button data-track="${esc(c.tracking_id)}">${esc(c.tracking_id)}</button> — ${esc(c.status)} — ${esc(c.priority)} — ${esc(c.sub_category)}</div>`).join(""):"<p>No complaints currently assigned.</p>";
  document.querySelectorAll("[data-track]").forEach(b=>b.onclick=()=>{$("track").value=b.dataset.track;trackComplaint()});
 }catch(e){$("dash").textContent=e.message}
}
$("refresh").onclick=refreshDashboard;
setInterval(()=>{if(session&&["mentor","administration","hod","dean","managing_director","vice_chancellor"].includes(session.role))refreshDashboard()},5000);
renderSession();
