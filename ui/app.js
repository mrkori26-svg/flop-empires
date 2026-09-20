const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
let state=null,selected=null,layer='ownership',refreshTimer=null,me=null;
let view={x:0,y:0,w:900,h:900},drag=null,currentCommand=null;
const enc=new TextEncoder(), SEED_RE=/^[0-9a-fA-F]{64}$/;
const PKCS8_ED25519=[0x30,0x2e,0x02,0x01,0x00,0x30,0x05,0x06,0x03,0x2b,0x65,0x70,0x04,0x22,0x04,0x20];
const MULTICODEC_ED25519=[0xed,0x01], B58='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
const PRF_SALT=enc.encode('flop-empires/did:key/v1');
const fmt=n=>new Intl.NumberFormat('en-US').format(Number(n||0));
const time=t=>new Date(Number(t)*1000).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function toast(text){const el=$('#toast');el.textContent=text;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),1800)}
function canonical(obj){const sort=x=>Array.isArray(x)?x.map(sort):x&&typeof x==='object'?Object.fromEntries(Object.keys(x).sort().map(k=>[k,sort(x[k])])):x;return JSON.stringify(sort(obj))}
function bytesB64u(buf){const b=new Uint8Array(buf);let s='';for(const x of b)s+=String.fromCharCode(x);return btoa(s).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'')}
function hexBytes(hex){if(!SEED_RE.test(hex))throw Error('seed must be exactly 64 hex characters');const out=new Uint8Array(32);for(let i=0;i<32;i++)out[i]=parseInt(hex.slice(i*2,i*2+2),16);return out}
function hexOf(bytes){return [...bytes].map(x=>x.toString(16).padStart(2,'0')).join('')}

function base58(bytes){let n=0n,out='';for(const b of bytes)n=n*256n+BigInt(b);while(n>0n){out=B58[Number(n%58n)]+out;n/=58n}let z=0;while(z<bytes.length&&bytes[z]===0){out='1'+out;z++}return out||'1'}
function didOf(pub){const raw=new Uint8Array(34);raw.set(MULTICODEC_ED25519);raw.set(pub,2);return 'did:key:z'+base58(raw)}
async function keyFromSeed(seedBytes,provider='seed'){
  const pkcs8=new Uint8Array(PKCS8_ED25519.length+32);pkcs8.set(PKCS8_ED25519);pkcs8.set(seedBytes,PKCS8_ED25519.length);
  const key=await crypto.subtle.importKey('pkcs8',pkcs8,'Ed25519',true,['sign']);
  const jwk=await crypto.subtle.exportKey('jwk',key);
  const b64=jwk.x.replace(/-/g,'+').replace(/_/g,'/');const pub=Uint8Array.from(atob(b64+'='.repeat((4-b64.length%4)%4)),c=>c.charCodeAt(0));
  return {did:didOf(pub),key,seed:hexOf(seedBytes),provider};
}
function randomBytes(n=32){const b=new Uint8Array(n);crypto.getRandomValues(b);return b}
async function derivePasskey(create=false){
  if(!window.PublicKeyCredential||!navigator.credentials)throw Error('Passkeys unavailable in this browser');
  let allow;
  if(create){const cred=await navigator.credentials.create({publicKey:{challenge:randomBytes(),rp:{name:'FLOP Empires'},user:{id:randomBytes(),name:'FLOP Empires player',displayName:'FLOP Empires player'},pubKeyCredParams:[{type:'public-key',alg:-8},{type:'public-key',alg:-7}],authenticatorSelection:{residentKey:'required',userVerification:'required'},extensions:{prf:{}}}});allow=[{type:'public-key',id:cred.rawId}]}
  const assertion=await navigator.credentials.get({publicKey:{challenge:randomBytes(),userVerification:'required',...(allow?{allowCredentials:allow}:{}),extensions:{prf:{eval:{first:PRF_SALT}}}}});
  const prf=assertion&&assertion.getClientExtensionResults().prf;
  if(!prf||!prf.results||!prf.results.first)throw Error('This passkey did not return PRF output');
  return keyFromSeed(new Uint8Array(prf.results.first).slice(0,32),'passkey');
}
async function api(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json().catch(()=>({}));if(!r.ok)throw Error(data.error||`HTTP ${r.status}`);return data}
async function authenticate(identity){const ch=await api('/api/auth/challenge',{did:identity.did});const sig=bytesB64u(await crypto.subtle.sign('Ed25519',identity.key,enc.encode(ch.message)));await api('/api/auth/verify',{challenge_id:ch.challenge_id,did:identity.did,signature:sig});me=identity;await load();toast('Identity authenticated')}

function viewerDid(){return state?.viewer?.did||me?.did||''}
function myEmpire(){const id=state?.viewer?.empire_id;return id?state.world.empires.find(e=>e.id===id):null}
async function load(){try{const r=await fetch('/api/state',{cache:'no-store'});if(!r.ok)throw Error(`HTTP ${r.status}`);state=await r.json();render()}catch(e){$('#statusText').textContent='UI offline';console.error(e)}}
function render(){renderHeader();renderStats();renderRecovery();renderPrelaunch();renderMap();renderEmpires();renderWar();renderActivity();renderRules();renderIdentity();renderPlayer();renderAlliances();renderReplay();renderOps();if(selected)renderTerritory(selected)}
function renderHeader(){const s=state.season,emp=myEmpire();const sub=$('.brand small');if(sub)sub.textContent=s.recovery?.active?'Season 0 · Recovery v1':'Season 0 · Technocore';$('#statusText').textContent=s.status;$('#statusDot').classList.toggle('live',['REGISTRATION','ACTIVE'].includes(s.status));$('#countdown').textContent=s.status==='REGISTRATION'?` · launch not authorized`:s.status==='ACTIVE'?` · ends ${time(s.season_end)}`:'';$('#identityButton').textContent=emp?emp.name:state.viewer.authenticated?'Authenticated':'Identity';document.title=`FLOP Empires · ${s.status}`}


function switchTab(name){const target=document.querySelector('.tab[data-tab="'+name+'"]');if(!target)return;document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x===target));document.querySelectorAll('.tab-panel').forEach(p=>p.classList.toggle('active',p.dataset.panel===name));document.querySelector('.more-tabs')?.removeAttribute('open')}
function renderPrelaunch(){const el=$('#prelaunchPanel'),s=state?.season,v=state?.viewer||{},emp=myEmpire(),claimed=state.world.empires.filter(e=>e.claimed).length;if(!el)return;if(s.status!=='REGISTRATION'){el.hidden=true;el.innerHTML='';const lock=$('#gameplayLock');if(lock)lock.textContent='';return}el.hidden=false;const player=emp?('Registered · '+esc(emp.name)):(v.authenticated?'Identity ready · choose an empire':'Observer mode');const action=emp?'<button class="prelaunch-cta" data-prelaunch="player">Open player dashboard</button>':'<button class="prelaunch-cta" data-prelaunch="empires">Choose an empire</button>';const s1=v.authenticated?'done':'',s2=emp?'done':'',s3=emp?'ready':'';el.innerHTML='<div class="prelaunch-copy"><span class="eyebrow">PRE-LAUNCH</span><h2>Season 0 is not live yet</h2><p>Gameplay stays locked until a separate signed launch authorization exists. You can explore, authenticate, and claim an empire now.</p><div class="onboarding-steps"><span class="'+s1+'">1 · Identity</span><span class="'+s2+'">2 · Choose empire</span><span class="'+s3+'">3 · Ready for launch</span></div></div><div class="prelaunch-actions"><div><strong>'+player+'</strong><small>'+claimed+'/16 empire slots claimed · launch not authorized</small></div>'+action+'<button class="ghost-btn" data-prelaunch="map">Explore map</button></div>';$$('[data-prelaunch]',el).forEach(b=>b.onclick=()=>switchTab(b.dataset.prelaunch));const lock=$('#gameplayLock');if(lock)lock.textContent='● GAMEPLAY LOCKED · LAUNCH NOT AUTHORIZED'}

function renderRecovery(){const el=$('#recoveryBanner'),r=state?.season?.recovery;if(!el)return;if(!r?.active){el.hidden=true;el.innerHTML='';return}el.hidden=false;const reasons=(r.reason_codes||[]).map(x=>x.replaceAll('_',' ').toLowerCase()).join(' · ');el.innerHTML=`<div><span class="eyebrow">RECOVERY V1</span><strong>Season 0 resumed under a signed recovery record</strong><small>${esc(reasons)}</small></div><div class="recovery-meta"><span>Recovery</span><code>${esc(r.recovery_id)}</code><span>Supersedes</span><code>${esc(r.original_activation_id)}</code><a href="${esc(r.evidence_url)}" target="_blank" rel="noreferrer">Public evidence ↗</a></div>`}
function renderStats(){const s=state,w=state.world,a=state.activity,claimed=w.empires.filter(e=>e.claimed).length;const cards=[['Phase',s.status,s.status==='REGISTRATION'?'Launch authorization required':`Season 0 · ${time(s.season_start)}`],['Registered',state.registration.actors,`${claimed}/16 empire slots claimed`],['World','64 territories',w.live_materialized?'Live materialized':'Frozen baseline'],['Open attacks',a.active_attacks.length,`${a.active_alliances.length} active alliances`]];$('#heroStats').innerHTML=cards.map(([k,v,x])=>`<div class="stat"><span>${esc(k)}</span><strong>${esc(v)}</strong><small>${esc(x)}</small></div>`).join('')}
function regionMarkup(){const groups={};for(const t of state.world.territories)(groups[t.region]??=[]).push(t);return Object.entries(groups).map(([name,items])=>{const cx=items.reduce((a,t)=>a+t.x,0)/items.length,cy=items.reduce((a,t)=>a+t.y,0)/items.length;return `<g class="region"><circle class="region-zone" cx="${cx}" cy="${cy}" r="105"/><text class="region-label" x="${cx}" y="${cy+118}">${name.toUpperCase()}</text></g>`}).join('')}
function neighbors(id){const n=[];for(const [a,b] of state.world.edges){if(a===id)n.push(b);else if(b===id)n.push(a)}return n.sort()}

function renderMap(){const svg=$('#worldMap'),viewport=$('#viewport'),byId=Object.fromEntries(state.world.territories.map(t=>[t.id,t]));const mine=myEmpire()?.id||null,conflict=new Set(state.activity.active_attacks.flatMap(a=>[a.origin_id,a.target_id])),reconned=new Set((state.viewer?.recon_intel||[]).map(x=>x.territory_id));let out=regionMarkup();for(const [a,b] of state.world.edges){const A=byId[a],B=byId[b];if(A&&B)out+=`<line class="edge" x1="${A.x}" y1="${A.y}" x2="${B.x}" y2="${B.y}"/>`}for(const atk of state.activity.active_attacks){const A=byId[atk.origin_id],B=byId[atk.target_id];if(A&&B)out+=`<line class="attack-line" x1="${A.x}" y1="${A.y}" x2="${B.x}" y2="${B.y}"/>`}for(const t of state.world.territories){const classes=['territory',t.capital?'capital':'',t.strategic_value>1?'strategic':'',mine&&t.owner===mine?'mine':'enemy',conflict.has(t.id)?'in-conflict':'',reconned.has(t.id)?'reconned':'',selected===t.id?'selected':''].filter(Boolean).join(' ');const r=t.capital?17:t.strategic_value>1?14:11;out+=`<g class="${classes}" data-id="${t.id}" tabindex="0" role="button"><circle class="node" cx="${t.x}" cy="${t.y}" r="${r}" fill="${t.color}"/>${t.capital?`<circle class="ring" cx="${t.x}" cy="${t.y}" r="${r+6}"/>`:''}${t.strategic_value>1?`<text x="${t.x}" y="${t.y}">✦</text>`:''}</g>`}viewport.innerHTML=out;svg.setAttribute('viewBox',`${view.x} ${view.y} ${view.w} ${view.h}`);const card=$('.map-card');card.classList.remove('layer-regions','layer-strategic','layer-conflict');if(layer!=='ownership')card.classList.add(`layer-${layer}`);$$('.territory',viewport).forEach(el=>{const pick=()=>{selected=el.dataset.id;renderMap();renderTerritory(selected)};el.onclick=pick;el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();pick()}}});$('#worldNotice').textContent=state.viewer.authenticated?'Authenticated view · own private values only.':'Public fog-safe projection.'}
function renderTerritory(id){
 const t=state.world.territories.find(x=>x.id===id);if(!t)return;
 const mine=myEmpire()?.id||null,owned=mine&&t.owner===mine,priv=t.private||null,atk=state.activity.active_attacks.find(a=>a.target_id===id||a.origin_id===id);
 const active=state.season.status==='ACTIVE'&&state.viewer?.authenticated&&!!mine,eng=Number(state.viewer?.economy?.engineering||0);
 const adjacentOwned=neighbors(id).some(n=>state.world.territories.find(x=>x.id===n)?.owner===mine);
 const canRecon=active,canFortify=active&&owned&&eng>0,canRaid=active&&!owned&&adjacentOwned&&eng>=14,canSiege=active&&!owned&&!t.capital&&adjacentOwned&&eng>=24;
 const disabled=(ok,why)=>ok?'':`disabled title="${esc(why)}"`;
 const fort=priv?fmt(priv.fortification):'Hidden by fog',prod=priv?fmt(priv.production?.ENGINEERING||0)+' ENG':'Hidden by fog';
 $('#territoryDetail').innerHTML=`<div class="detail-title"><div><span class="eyebrow">${esc(t.region.toUpperCase())}</span><h2>${esc(t.id)}${owned?'<span class="my-badge">MY TERRITORY</span>':''}</h2></div><span>${t.capital?'◆ CAPITAL':t.strategic_value>1?'✦ STRATEGIC':''}</span></div><div class="owner-pill"><i style="background:${t.color}"></i>${esc(t.owner_name)}</div><div class="kv"><div><span>Strategic value</span><strong>${fmt(t.strategic_value)}</strong></div><div><span>Fortification</span><strong>${fort}</strong></div><div><span>Production</span><strong>${prod}</strong></div><div><span>State</span><strong>${t.live?'Canonical live':'Frozen baseline'}</strong></div></div><div class="neighbors">${neighbors(id).map(n=>`<button class="chip" data-neighbor="${n}">${n}</button>`).join('')}</div>${atk?`<div class="world-notice">Open ${esc(atk.kind)} · deadline ${time(atk.deadline_at)}</div>`:''}<div class="detail-actions"><button class="action-btn" data-action="recon" ${disabled(canRecon,'Authenticate, join an empire, and wait for ACTIVE season')}>Recon</button>${owned?`<button class="action-btn" data-action="fortify" ${disabled(canFortify,'Requires ACTIVE season and unlocked Engineering')}>Fortify</button>`:`<button class="action-btn" data-action="raid" ${disabled(canRaid,'Requires ACTIVE season, 14+ Engineering and an owned adjacent origin')}>Raid</button><button class="action-btn" data-action="siege" ${disabled(canSiege,t.capital?'Capitals cannot be conquered':'Requires ACTIVE season, 24+ Engineering and an owned adjacent origin')}>Siege</button>`}</div>`;
 $$('[data-neighbor]').forEach(b=>b.onclick=()=>{selected=b.dataset.neighbor;renderMap();renderTerritory(selected)});$$('[data-action]:not([disabled])').forEach(b=>b.onclick=()=>openAction(b.dataset.action,t));
}

function renderEmpires(){const mine=myEmpire()?.id||null,sorted=[...state.world.empires].sort((a,b)=>Number(b.claimed)-Number(a.claimed)||a.id.localeCompare(b.id));$('#empireGrid').innerHTML=sorted.map(e=>`<article class="empire-card ${e.claimed?'':'unclaimed'}"><header><h3>${esc(e.name)}${e.id===mine?'<span class="my-badge">MINE</span>':''}</h3><span class="swatch" style="background:${e.color}"></span></header><div class="power">${esc(e.standing||'Unranked')}</div><small class="muted">${e.claimed?`${e.members} member${e.members===1?'':'s'}`:'open Season 0 slot'}</small><div class="resource-row"><div><small>PRESTIGE</small><strong>${fmt(e.prestige_public)}</strong></div><div><small>FOG</small><strong>ON</strong></div><div><small>SLOT</small><strong>${e.claimed?'CLAIMED':'OPEN'}</strong></div></div>${!e.claimed&&state.season.status==='REGISTRATION'?`<button class="action-btn claim-inline" data-claim="${e.id}">Join</button>`:''}</article>`).join('');$$('[data-claim]').forEach(b=>b.onclick=()=>openJoin(b.dataset.claim))}

function renderWar(){const list=state.activity.active_attacks;if(!list.length){$('#warList').innerHTML='<div class="empty-state">No open Raid or Siege windows.</div>';return}$('#warList').innerHTML=list.map(a=>`<article class="list-item"><div class="event-icon">${a.kind==='SIEGE'?'S':'R'}</div><div><strong>${esc(a.attacker_empire_id)} → ${esc(a.defender_empire_id)}</strong><small>${esc(a.origin_id)} → ${esc(a.target_id)} · force hidden by fog</small></div><time>${time(a.deadline_at)}</time></article>`).join('')}
function renderActivity(){const list=state.activity.recent_events;if(!list.length){$('#activityList').innerHTML='<div class="empty-state">No canonical game events yet.</div>';return}$('#activityList').innerHTML=list.map(e=>`<article class="list-item"><div class="event-icon">${e.accepted?'✓':'×'}</div><div><strong>${esc(e.event_type)}</strong><small>${esc(e.request_id)} · event #${fmt(e.seq)}</small></div><time>${time(e.accepted_at)}</time></article>`).join('')}
function renderRules(){const c=state.capabilities||{},e=state.evidence||{},r=state.season?.recovery;const caps=[['Fog-safe public projection',c.fog_safe_public_projection],['Signed private view',c.signed_private_view],['Raid / Siege',c.raid_siege],['Recon',c.recon],['Alliances runtime',c.alliances_runtime],['Treaties runtime',c.treaties_runtime_materialized],['Trade runtime',c.trade_runtime_materialized],['Standing runtime',c.standing_runtime_materialized]];$('#capabilityGrid').innerHTML=caps.map(([name,on])=>`<article class="empire-card"><header><h3>${esc(name)}</h3><span class="status-dot ${on?'live':''}"></span></header><div class="power">${on?'Available':'Not materialized'}</div></article>`).join('');$('#proofCard').innerHTML=`<div><span class="eyebrow">PUBLIC EVIDENCE</span><h3>${esc(e.projection_schema||'unknown')}</h3></div><div class="proof-grid"><span>Manifest</span><code>${esc(e.manifest_hash||'—')}</code><span>World</span><code>${esc(e.world_hash||'—')}</code><span>Event head</span><code>${esc(e.event_head_hash||'none')}</code><span>State hash</span><code>${esc(e.state_after_hash||'none')}</code>${r?.active?`<span>Recovery</span><code>${esc(r.recovery_id)}</code><span>Original activation</span><code>${esc(r.original_activation_id)}</code><span>Failed state</span><code>${esc(r.failed_state_hash)}</code>`:''}</div><p class="muted">${esc(e.claim||'')}</p>${r?.active?`<p><a class="proof-link" href="${esc(r.evidence_url)}" target="_blank" rel="noreferrer">Open Season 0 recovery evidence ↗</a></p>`:''}`}`
function renderIdentity(){const v=state.viewer||{},emp=myEmpire(),econ=v.economy;let step='Observer mode';if(v.authenticated&&!v.registered)step='Step 1/2 · register actor';else if(v.authenticated&&v.registered&&!v.empire_id)step='Step 2/2 · join an empire';else if(v.authenticated&&v.empire_id)step='Ready to play';$('#identityStatus').innerHTML=v.authenticated?`<strong>${esc(step)} ${emp?`· ${esc(emp.name)}`:''}</strong><br><span class="muted">${esc(v.did)}</span>${me?`<br><span class="muted">Signing key loaded in memory via ${esc(me.provider)}</span>`:'<br><span class="muted">Session valid; recover/import the key again before signing actions.</span>'}${!v.registered?'<br><button class="action-btn" id="registerNow">Register actor</button>':''}`:'<strong>Observer mode</strong><br><span class="muted">Authenticate with a passkey or existing 64-hex seed.</span>';$('#privateSummary').innerHTML=econ?`<div class="resource-row"><div><small>ENGINEERING</small><strong>${fmt(econ.engineering)}</strong></div><div><small>KNOWLEDGE</small><strong>${fmt(econ.knowledge)}</strong></div><div><small>INFLUENCE</small><strong>${fmt(econ.influence)}</strong></div></div>`:'';$('#claimGrid').innerHTML=state.world.empires.map(e=>`<button class="claim-btn" data-join="${e.id}" ${v.empire_id?'disabled':''}><span><strong>${esc(e.name)}</strong><small class="muted">${e.members} member${e.members===1?'':'s'}</small></span><i style="background:${e.color}"></i></button>`).join('');$$('[data-join]').forEach(b=>b.onclick=()=>openJoin(b.dataset.join));const reg=$('#registerNow');if(reg)reg.onclick=openRegister;$('#logoutIdentity').hidden=!v.authenticated;$('#copyIdentitySeed').hidden=!me?.seed}
function openSheet(id){$$('.command-sheet').forEach(s=>{const on=s.id===id;s.classList.toggle('open',on);s.setAttribute('aria-hidden',String(!on))})}
function closeSheets(){$$('.command-sheet').forEach(s=>{s.classList.remove('open');s.setAttribute('aria-hidden','true')})}
function uid(prefix){return `season0-${prefix}-${crypto.randomUUID().slice(0,12)}`}
function wrap(command){return {season_id:state.season.id,command}}
function setCommand(title,hint,builder,fields=''){currentCommand={builder};$('#commandTitle').textContent=title;$('#commandHint').textContent=hint;$('#commandForm').innerHTML=fields;const update=()=>{const text=canonical(wrap(builder()));$('#commandPreview').textContent=text;$('#commandSheet').dataset.command=text};$$('#commandForm input,#commandForm select').forEach(el=>el.addEventListener('input',update));update();$('#sendStatus').textContent='';openSheet('commandSheet')}

function actorDid(){return state.viewer?.did||me?.did||'YOUR_DID'}
function openRegister(){const req=uid('register');setCommand('Register actor','Register this authenticated DID for Season 0.',()=>({action:'register_actor',actor_did:actorDid(),payload:{},request_id:req}))}
function openJoin(empireId){const req=uid('join');setCommand('Join empire','Registration must exist first. Membership is frozen once Season 0 starts.',()=>({action:'join_empire',actor_did:actorDid(),payload:{empire_id:empireId},request_id:req}),`<label class="field wide"><span>Empire</span><input id="fEmpire" value="${esc(empireId)}" readonly /></label>`)}
function openAction(kind,t){const did=actorDid(),mine=myEmpire()?.id||null;if(kind==='recon'){const req=uid('recon');setCommand('Recon territory','Signed ACTIVE-season recon; returned intel expires under the frozen rule.',()=>({action:'recon',actor_did:did,payload:{territory_id:t.id},request_id:req}));return}if(kind==='fortify'){const req=uid('fortify');setCommand('Fortify territory','Spend unlocked Engineering on a territory your empire owns.',()=>({action:'fortify',actor_did:did,payload:{territory_id:t.id,amount:Number($('#fAmount')?.value||12)},request_id:req}),'<label class="field wide"><span>Engineering amount</span><input id="fAmount" type="number" min="1" value="12" /></label>');return}const origins=neighbors(t.id).map(id=>state.world.territories.find(x=>x.id===id)).filter(x=>x&&mine&&x.owner===mine);const isSiege=kind==='siege',min=isSiege?24:14,windowSec=isSiege?21600:1800,req=uid(kind),attackId=uid('attack');const opts=origins.length?origins.map(o=>`<option value="${o.id}">${o.id}</option>`).join(''):'<option value="YOUR_ADJACENT_TERRITORY">No owned adjacent territory detected</option>';const fields=`<label class="field"><span>Origin</span><select id="fOrigin">${opts}</select></label><label class="field"><span>Power</span><input id="fPower" type="number" min="${min}" value="${min}" /></label>`;setCommand(`${isSiege?'Siege':'Raid'} territory`,isSiege?'Siege may transfer an adjacent non-capital territory after the defense window.':'Raid opens the frozen defense window and cannot transfer territory.',()=>({action:'create_attack',actor_did:did,payload:{attack_id:attackId,origin_id:$('#fOrigin')?.value||'YOUR_ADJACENT_TERRITORY',target_id:t.id,kind:isSiege?'SIEGE':'RAID',power:Number($('#fPower')?.value||min),deadline_seconds:windowSec},request_id:req}),fields)}
async function signAndSend(){try{if(!state.viewer?.authenticated)throw Error('Authenticate first');if(!me||me.did!==state.viewer.did)throw Error('Recover/import your signing key first');const text=$('#commandSheet').dataset.command||'';if(!text)throw Error('No command');if(text.includes('YOUR_'))throw Error('Complete all command fields first');const parsed=JSON.parse(text),requestId=parsed.command.request_id,room=state.season.actions_namespace,nonce=`${Date.now()}-${crypto.getRandomValues(new Uint32Array(1))[0]}`;const sig=bytesB64u(await crypto.subtle.sign('Ed25519',me.key,enc.encode(`${room}|${nonce}|${text}`)));$('#sendStatus').textContent='SIGNED → publishing…';const result=await api('/api/action',{did:me.did,sig,nonce,text});$('#sendStatus').textContent=`SIGNED → POSTED · upstream ${result.upstream_status}`;toast('Signed action published');pollReceipt(requestId);setTimeout(load,800)}catch(e){$('#sendStatus').textContent=String(e.message||e);toast('Action not sent')}}

function zoom(factor,cx=view.x+view.w/2,cy=view.y+view.h/2){const nw=Math.max(260,Math.min(900,view.w*factor)),nh=nw,rx=(cx-view.x)/view.w,ry=(cy-view.y)/view.h;view={x:cx-rx*nw,y:cy-ry*nh,w:nw,h:nh};renderMap()}
function resetView(){view={x:0,y:0,w:900,h:900};renderMap()}
function pointerToWorld(e){const svg=$('#worldMap'),r=svg.getBoundingClientRect();return {x:view.x+(e.clientX-r.left)/r.width*view.w,y:view.y+(e.clientY-r.top)/r.height*view.h}}
const svg=$('#worldMap');svg.addEventListener('wheel',e=>{e.preventDefault();const p=pointerToWorld(e);zoom(e.deltaY>0?1.12:.88,p.x,p.y)},{passive:false});svg.addEventListener('pointerdown',e=>{drag={id:e.pointerId,startX:e.clientX,startY:e.clientY,baseX:view.x,baseY:view.y};svg.setPointerCapture(e.pointerId);svg.classList.add('dragging')});svg.addEventListener('pointermove',e=>{if(!drag||drag.id!==e.pointerId)return;const r=svg.getBoundingClientRect();view.x=drag.baseX-(e.clientX-drag.startX)/r.width*view.w;view.y=drag.baseY-(e.clientY-drag.startY)/r.height*view.h;svg.setAttribute('viewBox',`${view.x} ${view.y} ${view.w} ${view.h}`)});svg.addEventListener('pointerup',e=>{if(drag?.id===e.pointerId){drag=null;svg.classList.remove('dragging')}});svg.addEventListener('pointercancel',()=>{drag=null;svg.classList.remove('dragging')});
$$('.tab').forEach(btn=>btn.addEventListener('click',()=>switchTab(btn.dataset.tab)));$$('[data-close-sheet]').forEach(b=>b.addEventListener('click',closeSheets));
$('#identityButton').onclick=()=>openSheet('identitySheet');$('#zoomIn').onclick=()=>zoom(.8);$('#zoomOut').onclick=()=>zoom(1.25);$('#resetView').onclick=resetView;$$('.filter').forEach(b=>b.onclick=()=>{layer=b.dataset.layer;$$('.filter').forEach(x=>x.classList.toggle('active',x===b));renderMap()});
$('#copyCommand').onclick=async()=>{try{await navigator.clipboard.writeText($('#commandSheet').dataset.command||'');toast('Canonical JSON copied')}catch{toast('Copy unavailable')}};$('#signSendCommand').onclick=signAndSend;
$('#createPasskey').onclick=async()=>{try{await authenticate(await derivePasskey(true))}catch(e){toast(String(e.message||e))}};$('#recoverPasskey').onclick=async()=>{try{await authenticate(await derivePasskey(false))}catch(e){toast(String(e.message||e))}};
$('#useSeed').onclick=async()=>{try{const raw=$('#seedInput').value.trim();$('#seedInput').value='';await authenticate(await keyFromSeed(hexBytes(raw),'seed'))}catch(e){toast(String(e.message||e))}};
$('#copyIdentitySeed').onclick=async()=>{if(!me?.seed)return;try{await navigator.clipboard.writeText(me.seed);toast('Recovery seed copied — treat it like a password')}catch{toast('Seed not copied')}};
$('#logoutIdentity').onclick=async()=>{try{await api('/api/auth/logout',{});me=null;await load();toast('Signed out')}catch(e){toast(String(e.message||e))}};
window.addEventListener('keydown',e=>{if(e.key==='Escape')closeSheets()});
load();refreshTimer=setInterval(load,10000);

async function pollReceipt(requestId){
  for(let i=0;i<18;i++){
    await new Promise(r=>setTimeout(r,1500));
    try{
      const r=await fetch(`/api/receipt/${encodeURIComponent(requestId)}`,{cache:'no-store'});
      const data=await r.json();
      if(r.status===404){$('#sendStatus').textContent='SIGNED → POSTED → waiting for referee…';continue}
      if(!r.ok)throw Error(data.error||`HTTP ${r.status}`);
      const accepted=data.receipt?.accepted;
      const pub=data.publication;
      let text=`SIGNED → POSTED → ${accepted?'ACCEPTED':'REJECTED'} by referee`;
      if(pub?.status==='PUBLISHED')text+=' → receipt published';
      if(pub?.readback_verified)text+=' → READBACK VERIFIED';
      $('#sendStatus').textContent=text;await load();return data;
    }catch(e){$('#sendStatus').textContent=`Receipt tracking: ${e.message||e}`;return}
  }
  $('#sendStatus').textContent='POSTED · referee receipt still pending';return null;
}

function openDefense(attack){
  const req=uid('defense');
  setCommand('Submit defense','Lock Engineering into this open defense window.',()=>({action:'submit_defense',actor_did:actorDid(),payload:{attack_id:attack.id,amount:Number($('#fDefense')?.value||1)},request_id:req}),'<label class="field wide"><span>Engineering defense</span><input id="fDefense" type="number" min="1" value="10" /></label>');
}
function openCreateAlliance(){
  const req=uid('alliance'), mine=myEmpire()?.id||'YOUR_EMPIRE';
  setCommand('Create alliance','Creates an inactive defensive alliance. A member must activate it separately.',()=>({action:'create_alliance',actor_did:actorDid(),payload:{alliance_id:$('#fAlliance')?.value||uid('alliance-id'),members:($('#fMembers')?.value||'').split(',').map(x=>x.trim()).filter(Boolean)},request_id:req}),`<label class="field"><span>Alliance id</span><input id="fAlliance" value="${uid('alliance-id')}" /></label><label class="field wide"><span>Empire IDs, comma separated</span><input id="fMembers" value="${mine}," /></label>`);
}
function openAllianceActive(allianceId,active){
  const req=uid(active?'activate-alliance':'deactivate-alliance');
  setCommand(active?'Activate alliance':'Deactivate alliance','Signed alliance-state command.',()=>({action:'set_alliance_active',actor_did:actorDid(),payload:{alliance_id:allianceId,active},request_id:req}));
}

let replayData=null,opsData=null,scoreData=null;
async function ensureAux(){
  try{
    const [rr,oo,ss]=await Promise.all([fetch('/api/replay',{cache:'no-store'}),fetch('/api/readiness',{cache:'no-store'}),fetch('/api/scoreboard',{cache:'no-store'})]);
    if(rr.ok)replayData=await rr.json();if(oo.ok)opsData=await oo.json();if(ss.ok)scoreData=await ss.json();
  }catch(e){console.warn('aux data unavailable',e)}
}
function renderPlayer(){
  const el=$('#playerDashboard');if(!el)return;
  const v=state.viewer||{},emp=myEmpire(),econ=v.economy,bal=v.balance;
  if(!v.authenticated){el.innerHTML='<div class="empty-state">Authenticate to open the private player dashboard.</div>';return}
  if(!emp){el.innerHTML=`<article class="panel-card"><h3>Onboarding</h3><p class="muted">DID authenticated, but no empire membership exists yet.</p><button class="action-btn" id="playerRegister">Register actor</button><p class="muted">Then select an open empire in Empires.</p></article>`;const b=$('#playerRegister');if(b)b.onclick=openRegister;return}
  const power=(econ?.engineering||0)+(econ?.knowledge||0)+(econ?.influence||0);
  const incoming=v.incoming_attacks||[], outgoing=v.outgoing_attacks||[], intel=v.recon_intel||[];
  el.innerHTML=`<article class="panel-card"><span class="eyebrow">${esc(emp.name)}</span><h3>Private economy</h3><div class="power">POWER ${fmt(power)}</div><div class="resource-row"><div><small>ENGINEERING</small><strong>${fmt(econ?.engineering)}</strong></div><div><small>KNOWLEDGE</small><strong>${fmt(econ?.knowledge)}</strong></div><div><small>INFLUENCE</small><strong>${fmt(econ?.influence)}</strong></div></div><p class="muted">Unlocked combat balance: ${fmt(bal?.available)} · locked: ${fmt(bal?.locked)}</p></article>`+
  `<article class="panel-card"><h3>Incoming attacks</h3>${incoming.length?incoming.map(a=>`<div class="mini-row"><span>${esc(a.kind)} · ${esc(a.target_id)}</span><button class="action-btn" data-defend="${esc(a.id)}">Defend</button><small>${time(a.deadline_at)}</small></div>`).join(''):'<p class="muted">No open attacks against your empire.</p>'}</article>`+
  `<article class="panel-card"><h3>Recon intel</h3>${intel.length?intel.map(i=>`<div class="mini-row"><span>${esc(i.territory_id)} · fort ${fmt(i.fortification)}</span><small>expires ${time(i.expires_at)}</small></div>`).join(''):'<p class="muted">No unexpired recon snapshots.</p>'}</article>`+
  `<article class="panel-card"><h3>Outgoing fronts</h3>${outgoing.length?outgoing.map(a=>`<div class="mini-row"><span>${esc(a.kind)} ${esc(a.origin_id)} → ${esc(a.target_id)}</span><small>${a.defense_submissions} defense submission(s)</small></div>`).join(''):'<p class="muted">No open attacks.</p>'}</article>`;
  $$('[data-defend]',el).forEach(b=>b.onclick=()=>openDefense(incoming.find(a=>a.id===b.dataset.defend)));
}

function renderAlliances(){
  const el=$('#allianceDashboard');if(!el)return;const v=state.viewer||{},mine=myEmpire()?.id;
  if(!v.authenticated||!mine){el.innerHTML='<div class="empty-state">Authenticate and join an empire to manage alliances.</div>';return}
  const memberships=state.activity.alliance_members||[],all=state.activity.alliances||[],mineIds=new Set(memberships.filter(m=>m.empire_id===mine).map(m=>m.alliance_id));
  const cards=all.filter(a=>mineIds.has(a.id)).map(a=>{const members=memberships.filter(m=>m.alliance_id===a.id).map(m=>m.empire_id);return `<article class="panel-card"><h3>${esc(a.id)}</h3><p class="muted">${members.map(esc).join(' · ')}</p><div class="power">${a.active?'ACTIVE':'INACTIVE'}</div><button class="action-btn" data-alliance-toggle="${esc(a.id)}" data-next="${a.active?'0':'1'}">${a.active?'Deactivate':'Activate'}</button></article>`}).join('');
  el.innerHTML=`<article class="panel-card"><h3>Create defensive alliance</h3><p class="muted">Runtime limit: at most two active defensive alliances per empire. Eligibility is snapshotted when an attack opens.</p><button class="action-btn" id="createAllianceBtn">Build create command</button></article>${cards||'<article class="panel-card"><p class="muted">No alliances for your empire yet.</p></article>'}<article class="panel-card"><h3>Not active in Season 0</h3><p class="muted">NAPs, bilateral treaties and trade are Gate B candidate mechanics and are intentionally not exposed as production actions.</p></article>`;
  $('#createAllianceBtn').onclick=openCreateAlliance;$$('[data-alliance-toggle]',el).forEach(b=>b.onclick=()=>openAllianceActive(b.dataset.allianceToggle,b.dataset.next==='1'));
}

function renderReplay(){
  const el=$('#replayDashboard'),slider=$('#replaySlider'),label=$('#replayLabel');if(!el||!slider||!label)return;
  const events=replayData?.events||[];slider.max=Math.max(0,events.length-1);if(Number(slider.value)>Number(slider.max))slider.value=slider.max;
  if(!events.length){el.innerHTML='<div class="empty-state">No canonical game events yet.</div>';label.textContent='';return}
  const idx=Number(slider.value||0),e=events[idx];label.textContent=`event ${e.seq} / ${events.at(-1).seq}`;
  el.innerHTML=`<article class="list-item"><div class="event-icon">${e.accepted?'✓':'×'}</div><div><strong>${esc(e.event_type)}</strong><small>${esc(e.request_id)}${e.origin_id?` · ${esc(e.origin_id)} → ${esc(e.target_id||'')}`:''}</small><code>${esc(e.state_before_hash.slice(0,12))}… → ${esc(e.state_after_hash.slice(0,12))}…</code></div><time>${time(e.accepted_at)}</time></article>`;
}

function renderOps(){
  const el=$('#opsDashboard');if(!el)return;if(!opsData){el.innerHTML='<div class="empty-state">Loading operational checks…</div>';return}
  const checks=Object.entries(opsData.checks||{}).map(([k,v])=>`<div class="check-row"><span>${esc(k.replaceAll('_',' '))}</span><strong class="${v?'ok-text':'bad-text'}">${v?'PASS':'FAIL'}</strong></div>`).join('');
  const ver=opsData.verification||{};const scoreRows=(scoreData?.rows||[]).slice(0,5);
  el.innerHTML=`<article class="panel-card"><span class="eyebrow">READINESS</span><h3>${opsData.ok?'READY':'ATTENTION REQUIRED'}</h3>${checks}<p class="muted">Pending receipts: ${fmt(opsData.pending_receipts)} · published without readback: ${fmt(opsData.published_unverified)}</p></article>`+
  `<article class="panel-card"><span class="eyebrow">VERIFIER</span><h3>${ver.ok?'Artifact chain verified':'Verification failure'}</h3><p class="muted">Events: ${fmt(ver.event_count)} · current state ${esc((ver.current_state_hash||'').slice(0,16))}…</p><code>${esc(ver.manifest_hash||'')}</code></article>`+
  `<article class="panel-card"><span class="eyebrow">DESCRIPTIVE ONLY</span><h3>Candidate scoreboard</h3><p class="muted">Not an authoritative victory rule. Gate B standing/victory is still not frozen.</p>${scoreRows.map((r,i)=>`<div class="mini-row"><span>${i+1}. ${esc(r.name)}</span><strong>${fmt(r.candidate_score)}</strong></div>`).join('')}</article>`;
}

$('#replaySlider')?.addEventListener('input',renderReplay);
ensureAux().then(()=>{renderReplay();renderOps()});setInterval(()=>ensureAux().then(()=>{renderReplay();renderOps()}),30000);

async function postSignedCommand(command){
  if(!state.viewer?.authenticated)throw Error('Authenticate first');
  if(!me||me.did!==state.viewer.did)throw Error('Recover/import your signing key first');
  const text=canonical(wrap(command)),room=state.season.actions_namespace;
  const nonce=`${Date.now()}-${crypto.getRandomValues(new Uint32Array(1))[0]}`;
  const sig=bytesB64u(await crypto.subtle.sign('Ed25519',me.key,enc.encode(`${room}|${nonce}|${text}`)));
  return api('/api/action',{did:me.did,sig,nonce,text});
}
async function waitReceipt(requestId,tries=20){
  for(let i=0;i<tries;i++){await new Promise(r=>setTimeout(r,1200));const r=await fetch(`/api/receipt/${encodeURIComponent(requestId)}`,{cache:'no-store'});if(r.status===404)continue;const d=await r.json();if(!r.ok)throw Error(d.error||`HTTP ${r.status}`);return d}return null;
}
async function onboardToEmpire(empireId){
  try{
    if(!state.viewer?.authenticated||!me)throw Error('Authenticate and load your signing key first');
    if(state.viewer.empire_id)throw Error('This DID already belongs to an empire');
    if(!state.viewer.registered){const req=uid('register');toast('Registering actor…');await postSignedCommand({action:'register_actor',actor_did:me.did,payload:{},request_id:req});const rr=await waitReceipt(req);if(!rr?.receipt?.accepted)throw Error(rr?.receipt?.details?.error||'Registration was not accepted');await load()}
    const req=uid('join');toast(`Joining ${empireId}…`);await postSignedCommand({action:'join_empire',actor_did:me.did,payload:{empire_id:empireId},request_id:req});const jr=await waitReceipt(req);if(!jr?.receipt?.accepted)throw Error(jr?.receipt?.details?.error||'Join was not accepted');await load();toast('Ready to play');
  }catch(e){toast(String(e.message||e))}
}
function actionAvailability(t,kind){
  const v=state.viewer||{},ctx=v.action_context||{},mine=myEmpire()?.id,owned=mine&&t.owner===mine,bal=Number(ctx.unlocked_engineering||0);
  if(!v.authenticated)return [false,'Authenticate first'];if(!mine)return [false,'Join an empire first'];if(state.season.status!=='ACTIVE')return [false,'Available when Season 0 is ACTIVE'];
  if(kind==='fortify')return owned&&bal>0?[true,'']:[false,owned?'No unlocked Engineering':'Territory not owned'];
  if(kind==='recon')return [true,''];
  const origins=neighbors(t.id).map(id=>state.world.territories.find(x=>x.id===id)).filter(x=>x&&x.owner===mine);
  if(owned)return [false,'Cannot attack your own territory'];if(kind==='siege'&&t.capital)return [false,'Capital conquest is forbidden'];if(!origins.length)return [false,'No owned adjacent origin'];const min=kind==='siege'?24:14;if(bal<min)return [false,`Need at least ${min} unlocked Engineering`];return [true,''];
}

function renderTerritory(id){
  const t=state.world.territories.find(x=>x.id===id);if(!t)return;const mine=myEmpire()?.id||null,owned=mine&&t.owner===mine,priv=t.private||null,atk=state.activity.active_attacks.find(a=>a.target_id===id||a.origin_id===id),intel=(state.viewer?.recon_intel||[]).find(x=>x.territory_id===id);
  const fort=priv?fmt(priv.fortification):intel?`${fmt(intel.fortification)} · recon`:'Hidden by fog',prod=priv?fmt(priv.production?.ENGINEERING||0)+' ENG':'Hidden by fog';
  const actions=owned?['recon','fortify']:['recon','raid','siege'];
  const buttons=actions.map(kind=>{const [ok,reason]=actionAvailability(t,kind);return `<button class="action-btn" data-action="${kind}" ${ok?'':`disabled title="${esc(reason)}"`}>${kind[0].toUpperCase()+kind.slice(1)}</button>${!ok?`<small class="action-reason">${esc(reason)}</small>`:''}`}).join('');
  $('#territoryDetail').innerHTML=`<div class="detail-title"><div><span class="eyebrow">${esc(t.region.toUpperCase())}</span><h2>${esc(t.id)}${owned?'<span class="my-badge">MY TERRITORY</span>':''}</h2></div><span>${t.capital?'◆ CAPITAL':t.strategic_value>1?'✦ STRATEGIC':''}</span></div><div class="owner-pill"><i style="background:${t.color}"></i>${esc(t.owner_name)}</div><div class="kv"><div><span>Strategic value</span><strong>${fmt(t.strategic_value)}</strong></div><div><span>Fortification</span><strong>${fort}</strong></div><div><span>Production</span><strong>${prod}</strong></div><div><span>State</span><strong>${t.live?'Canonical live':'Frozen baseline'}</strong></div></div>${intel?`<div class="world-notice">Recon intel expires ${time(intel.expires_at)}</div>`:''}<div class="neighbors">${neighbors(id).map(n=>`<button class="chip" data-neighbor="${n}">${n}</button>`).join('')}</div>${atk?`<div class="world-notice">Open ${esc(atk.kind)} · deadline ${time(atk.deadline_at)}</div>`:''}<div class="detail-actions">${buttons}</div>`;
  $$('[data-neighbor]').forEach(b=>b.onclick=()=>{selected=b.dataset.neighbor;renderMap();renderTerritory(selected)});$$('[data-action]:not([disabled])').forEach(b=>b.onclick=()=>openAction(b.dataset.action,t));
}
function renderEmpires(){
  const mine=myEmpire()?.id||null,v=state.viewer||{},sorted=[...state.world.empires].sort((a,b)=>Number(b.claimed)-Number(a.claimed)||a.id.localeCompare(b.id));
  $('#empireGrid').innerHTML=sorted.map(e=>{const canJoin=v.authenticated&&!v.empire_id&&state.season.status==='REGISTRATION',label=!v.registered?'Register & join':'Join',p=e.participation||{},badges=(p.badges||[]).map(x=>`<span class="merit-badge">${esc(x.replaceAll('_',' '))}</span>`).join('');return `<article class="empire-card ${e.claimed?'':'unclaimed'}"><header><h3>${esc(e.name)}${e.id===mine?'<span class="my-badge">MINE</span>':''}</h3><span class="swatch" style="background:${e.color}"></span></header><div class="power">${e.claimed?esc(p.band||'UNQUALIFIED'):'Unclaimed'}</div><small class="muted">${e.claimed?`${e.members} member${e.members===1?'':'s'} · participation profile`:'open Season 0 slot'}</small><div class="resource-row merit-row"><div><small>MERIT</small><strong>${fmt(p.player_merit||0)}</strong></div><div><small>ACTIVE EPOCHS</small><strong>${fmt(p.active_epochs||0)}</strong></div><div><small>TESTNET</small><strong>${p.early_testnet_eligible?'ELIGIBLE':'—'}</strong></div></div>${e.claimed?`<div class="badge-row">${badges||'<span class="muted">No badges yet</span>'}</div>`:''}<div class="resource-row"><div><small>PRESTIGE</small><strong>${fmt(e.prestige_public)}</strong></div><div><small>FOG</small><strong>ON</strong></div><div><small>SLOT</small><strong>${e.claimed?'CLAIMED':'OPEN'}</strong></div></div>${canJoin?`<button class="action-btn claim-inline" data-onboard="${e.id}">${label}</button>`:''}</article>`}).join('');$$('[data-onboard]').forEach(b=>b.onclick=()=>onboardToEmpire(b.dataset.onboard));
}
function focusTerritory(id){selected=id;$$('.tab').forEach(x=>x.classList.toggle('active',x.dataset.tab==='map'));$$('.tab-panel').forEach(p=>p.classList.toggle('active',p.dataset.panel==='map'));renderMap();renderTerritory(id);document.querySelector('.map-card')?.scrollIntoView({behavior:'smooth',block:'start'})}
function renderWar(){const list=state.activity.active_attacks;if(!list.length){$('#warList').innerHTML='<div class="empty-state">No open Raid or Siege windows.</div>';return}$('#warList').innerHTML=list.map(a=>`<article class="list-item clickable" data-war-focus="${esc(a.target_id)}"><div class="event-icon">${a.kind==='SIEGE'?'S':'R'}</div><div><strong>${esc(a.attacker_empire_id)} → ${esc(a.defender_empire_id)}</strong><small>${esc(a.origin_id)} → ${esc(a.target_id)} · ${a.defense_submissions} defense submission(s)</small></div><time>${time(a.deadline_at)}</time></article>`).join('');$$('[data-war-focus]').forEach(x=>x.onclick=()=>focusTerritory(x.dataset.warFocus))}
