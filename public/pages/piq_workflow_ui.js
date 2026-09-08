import {api} from '../api.js';
import {state} from '../state.js';
import {$, esc, modal, toast} from '../ui.js';

const key=()=>`rmr-piq-selection:${state.user?.id}:${state.selectedTenantId}`;
const read=()=>{try{return JSON.parse(sessionStorage.getItem(key()))||{};}catch{return {};}};
const save=v=>{try{sessionStorage.setItem(key(),JSON.stringify({...read(),...v}));}catch{}};
export const lines=value=>String(value||'').split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
export function quantity(value,max=50){const n=Number(value);if(!/^\d+$/.test(String(value))||!Number.isInteger(n)||n<1||n>Math.min(50,max))throw new Error('Choose a whole number from 1 to '+Math.min(50,max));return n;}
export const researchMessage = run => {
  const status=typeof run==='string'?run:run?.status;
  if(status==='no_evidence')return run?.summary?.outcome==='no_findings'?
    'Research completed, but no supporting findings were returned.':run?.summary?.outcome==='findings_rejected'?
    'Research completed, but the findings did not pass RMR evidence validation.':
    'Research completed with no accepted evidence. Detailed outcome counts are unavailable.';
  return ({
  awaiting_confirmation:'Research awaiting confirmation.',expired:'Research confirmation expired.',
  queued:'Adaptive Research queued…',running:'Researching additional public evidence…',
  retry_wait:'Research waiting to retry.',completed:'Adaptive Research completed.',
  partial:'Research completed with partial results.',
  failed:'Adaptive Research failed. No unsupported evidence was accepted.',cancelled:'Research cancelled.'
})[status]||'Research not yet run.';
};
export function researchDetails(run,row){
  if(!run||!['completed','partial','no_evidence'].includes(run.status))return '';
  const s=run.summary||{},value=n=>Number.isInteger(n)?n:'Not recorded';
  return `<section class="notice-card" data-piq-research-detail><h3>Adaptive Research Summary</h3>
    <p>${esc(researchMessage(run))}</p><p>Tasks researched: ${value(s.tasks_researched)} / ${value(s.tasks_planned??run.task_count)} planned (provider-reported)</p>
    <p>Tasks with evidence found: ${value(s.tasks_found)} · Tasks with no evidence found: ${value(s.tasks_not_found)}</p>
    <p>Returned findings: ${value(s.returned)} · Accepted findings: ${value(s.accepted)} · Rejected findings: ${value(s.rejected)}</p>
    <p>Research Adjustment: ${(row.adaptive_score_delta||0)>=0?'+':''}${esc(row.adaptive_score_delta||0)} · Final Match: ${esc(row.score)}</p>
    ${(s.tasks||[]).map(t=>`<p>${esc(t.criterion)}: ${esc(t.provider_outcome.replaceAll('_',' '))}${t.searched===false?' (not searched)':''} · Accepted: ${value(t.accepted)} · Rejected: ${value(t.rejected)}</p>`).join('')}
    ${Object.keys(s.reasons||{}).length?`<p>Validation reasons: ${Object.entries(s.reasons).map(([k,v])=>`${esc(k.replaceAll('_',' '))}: ${value(v)}`).join(' · ')}</p>`:''}
    ${s.tasks_researched==null?'<p>Historical run: per-task search coverage was not recorded.</p>':''}</section>`;
}
export function runSummary(run){
  if(!run)return 'No discovery runs yet.';
  const d=run.diagnostics||{};
  return `Status: ${run.status} · Requested: ${run.requested_count} · Provider candidates: ${d.provider_candidate_count??0} · Evaluated: ${d.evaluated_count??((d.rejected||0)+(run.result_count||0))} · Existing/duplicates: ${d.duplicates_skipped??d.duplicate_count??0} · Rejected: ${d.rejected??0} · New discovered prospects: ${run.result_count??0}`;
}
export async function loadWorkflow(tenantId){
  const stored=read();
  const collection=await api(`/api/tenants/${tenantId}/piq/target-profiles?include_archived=${stored.archived?'true':'false'}`);
  const profiles=collection.profiles;
  const profile=profiles.find(x=>x.id===stored.profileId)||profiles.find(x=>x.active)||profiles[0]||null;
  if(!profile)return {collection,profiles,profile:null,runs:[],data:{opportunities:[]},run:null,runId:'all'};
  const {runs}=await api(`/api/tenants/${tenantId}/piq/target-profiles/${profile.id}/runs`);
  const runId=stored.profileId===profile.id && (stored.runId==='all'||runs.some(r=>r.run_id===stored.runId))?stored.runId:runs[0]?.run_id||'all';
  const data=await api(`/api/tenants/${tenantId}/piq/target-profiles/${profile.id}/results${runId==='all'?'':`?run_id=${encodeURIComponent(runId)}`}`);
  save({profileId:profile.id,runId});
  return {collection,profiles,profile,runs,data,run:runs.find(r=>r.run_id===runId)||runs[0]||null,runId};
}
export function profileModal(profile,ctx,view=false){
  const tenantId=state.selectedTenantId;
  const listField=(label,name,value,required=false)=>`<div class="field full"><label>${label} (one per line)</label><textarea name="${name}" ${required?'required':''} ${view?'readonly':''}>${esc((value||[]).join('\n'))}</textarea></div>`;
  modal({title:view?'View Target Profile':'ProspectIQ Target Profile',wide:true,
    body:`<form id="piq-profile-form" class="form-grid">
    <div class="field full"><label>Profile name</label><input name="name" required maxlength="180" value="${esc(profile?.name||'')}" ${view?'readonly':''}></div>
    ${listField('Industries','industries',profile?.industries_json,true)}
    ${listField('Locations — commas stay within a location','locations',profile?.locations_json,true)}
    ${listField('Keywords','keywords',profile?.keywords_json)}
    ${listField('Exclusions','exclusions',profile?.exclusions_json)}
    ${[['Minimum employees','employee_min',profile?.employee_min||0],['Maximum employees (0 = unspecified)','employee_max',profile?.employee_max||0],['Minimum annual revenue','revenue',(profile?.revenue_min_cents||0)/100]].map(([label,name,value])=>`<div class="field"><label>${label}</label><input name="${name}" type="number" min="0" step="${name==='revenue'?'0.01':'1'}" value="${value}" ${view?'readonly':''}></div>`).join('')}
    <p class="field full">Employee count and revenue are stored targeting/research criteria, unresolved during Google discovery. Exclusions use observed category/industry or geography evidence, not arbitrary negative keywords. Maximum 25 items per list, 80 characters per item. Only the first two keywords refine searches; only the first four can add keyword score.</p></form>`,
    footer:`<button class="button secondary" data-close-modal>Close</button>${view?'':'<button class="button" id="piq-save-profile">Save Profile</button>'}`,
    onOpen:(root,close)=>$('#piq-save-profile',root)?.addEventListener('click',async event=>{
      const f=$('#piq-profile-form',root);if(!f.reportValidity())return;
      const value=name=>f.elements.namedItem(name).value;
      try{
        const payload={name:value('name').trim(),industries:lines(value('industries')),locations:lines(value('locations')),keywords:lines(value('keywords')),exclusions:lines(value('exclusions')),employee_min:Number(value('employee_min')),employee_max:Number(value('employee_max')),revenue_min_cents:Math.round(Number(value('revenue'))*100)};
        for(const name of ['industries','locations','keywords','exclusions'])if(payload[name].length>25||payload[name].some(x=>x.length>80))throw new Error('Maximum 25 items per list and 80 characters per item.');
        if(payload.employee_max && payload.employee_min>payload.employee_max)throw new Error('Maximum employees must be at least minimum employees.');
        if(state.selectedTenantId!==tenantId)throw new Error('Client context changed. Reopen the profile.');
        event.target.disabled=true;
        const result=await api(`/api/tenants/${tenantId}/piq/target-profiles${profile?'/'+profile.id:''}`,{method:profile?'PUT':'POST',body:payload});
        if(state.selectedTenantId===tenantId){save({profileId:result.profile.id,runId:'all'});toast('Target profile saved');close();ctx.navigate('piq');}
      }catch(e){toast(e.message,'error');event.target.disabled=false;}
    })});
}
export function bindWorkflow(page,workflow,ctx,button,readOnly=false){
  const w=workflow,editable=w.collection.can_write&&!readOnly,tenantId=state.selectedTenantId;
  const box=document.createElement('div');box.className='piq-workflow';box.dataset.piqWorkflow='';
  const selected=read(),max=Math.min(50,w.collection.max_requested_count);
  const n=Math.min(Number(selected.quantity)||10,max);
  const preset=[10,20,30,40,50].includes(n)?String(n):'custom';
  box.innerHTML=`<section class="card" data-piq-management>
  <div class="card-head"><div><h2>Saved Target Profiles</h2><p class="muted">Create and manage your prospect targeting profiles.</p></div>${editable?'<button class="button secondary" id="piq-create-profile">Create Target Profile</button>':''}</div>
  <div class="piq-management-row"><div class="field"><label for="piq-profile-select">Saved profile</label><select id="piq-profile-select">${w.profiles.map(p=>`<option value="${esc(p.id)}" ${p.id===w.profile?.id?'selected':''}>${esc(p.name)}${p.active?'':' (deleted)'} — ${esc(p.industries_json.join(', '))} · ${esc(p.locations_json.join(' / '))}</option>`).join('')}</select></div>
  <div class="piq-profile-actions">${w.profile?`<button class="button secondary small" id="piq-view-profile">View Profile</button>${editable&&w.profile.active?'<button class="button secondary small" id="piq-edit-profile">Edit Profile</button><button class="button secondary small" id="piq-delete-profile">Delete Profile</button>':''}`:''}</div></div>
  <label class="piq-archive-toggle"><input type="checkbox" id="piq-show-archived" ${selected.archived?'checked':''}> Include deleted profiles for history</label>
  ${w.profile?'':'<p>No saved profiles. Create one before pulling leads.</p>'}</section>
  <section class="card" data-piq-pull>
  <div class="card-head"><h2>Pull Leads</h2></div>
  <div class="piq-pull-row">
    <div class="field"><label for="piq-pull-profile-select">Target Profile</label><select id="piq-pull-profile-select">${!w.profile?.active?'<option value="" selected>Select an active profile</option>':''}${w.profiles.filter(p=>p.active).map(p=>`<option value="${esc(p.id)}" ${p.id===w.profile?.id?'selected':''}>${esc(p.name)}</option>`).join('')}</select></div>
    <div class="field"><label for="piq-quantity">Lead Quantity</label><select id="piq-quantity">${[10,20,30,40,50].map(q=>`<option value="${q}" ${q>max?'disabled':''} ${preset===String(q)?'selected':''}>${q}</option>`).join('')}<option value="custom" ${preset==='custom'?'selected':''}>Custom</option></select>
      <div class="field" id="piq-custom-wrap" ${preset!=='custom'?'hidden':''}><label for="piq-custom-quantity">Custom (1–${max})</label><input id="piq-custom-quantity" type="number" min="1" max="${max}" step="1" required value="${n}" aria-describedby="piq-quantity-help"></div>
    </div>
    <div class="piq-pull-action" data-piq-pull-action></div>
  </div>
  <p id="piq-quantity-help" aria-live="polite">Pull up to ${n} new discovered prospects. Fewer may be available within the search limits.</p>
  ${w.profile?`<div class="piq-selected-summary" data-piq-selected-summary><strong>${esc(w.profile.name)}${w.profile.active?'':' (deleted — history only)'}</strong><p><b>Industries:</b> ${esc(w.profile.industries_json.join(', '))} · <b>Locations:</b> ${esc(w.profile.locations_json.join(' / '))}</p>${w.profile.keywords_json.length?`<p><b>Keywords:</b> ${esc(w.profile.keywords_json.join(', '))}</p>`:''}</div>`:''}
  <div class="piq-pull-history" data-piq-history>
    <div class="piq-history-actions"><button class="button secondary small" id="piq-latest-pull" ${w.runs.length?'':'disabled'} aria-pressed="${w.runId===w.runs[0]?.run_id}">Latest Pull</button><button class="button secondary small" id="piq-all-leads" aria-pressed="${w.runId==='all'}">All Profile Leads</button></div>
    <div class="field"><label for="piq-run-select">Pull History</label><select id="piq-run-select"><option value="all" ${w.runId==='all'?'selected':''}>All historical results for this profile</option>${w.runs.map(r=>`<option value="${esc(r.run_id)}" ${r.run_id===w.runId?'selected':''}>${esc(r.created_at||r.run_id)} — ${esc(r.status)} — ${r.result_count} new</option>`).join('')}</select></div>
    <p data-piq-run-summary>${esc(runSummary(w.run))}</p><p class="muted">${w.runId==='all'?'Showing historical prospects for this profile.':'Showing only NEW prospects retained by the selected run; existing duplicates are not shown as new.'}</p>
  </div>
  <p class="muted">Discovery: ${w.collection.discovery_live?'Live Google Places':'Demonstration'} · Adaptive Research: ${w.collection.research_live?'Live OpenAI':'Demonstration'}</p>
  </section>`;
  const intro=page.querySelector('[data-piq-intro]');
  if(intro)intro.after(box);else page.prepend(box);
  if(button)$('[data-piq-pull-action]',box).append(button);
  if(!w.profile?.active)for(const el of page.querySelectorAll('#v53-edit-target,#edit-target'))el.remove();
  if(!editable)for(const el of page.querySelectorAll('[data-research-piq],[data-move-piq],#v53-import-piq'))el.hidden=true;
  if(w.collection.can_move===false)for(const el of page.querySelectorAll('[data-move-piq],[data-piq-crm]')){el.disabled=true;el.title='PIQ enhancement entitlement required for CRM handoff';}
  $('#piq-create-profile',box)?.addEventListener('click',()=>profileModal(null,ctx));
  $('#piq-view-profile',box)?.addEventListener('click',()=>profileModal(w.profile,ctx,true));
  $('#piq-edit-profile',box)?.addEventListener('click',()=>profileModal(w.profile,ctx));
  $('#piq-delete-profile',box)?.addEventListener('click',()=>modal({title:'Delete Profile',body:'Delete this profile from the active list? Historical runs, prospects and evidence will be preserved.',footer:'<button class="button secondary" data-close-modal>Cancel</button><button class="button" id="piq-confirm-delete">Delete Profile</button>',onOpen:(root,close)=>$('#piq-confirm-delete',root).addEventListener('click',async e=>{e.target.disabled=true;try{if(state.selectedTenantId!==tenantId)throw new Error('Client context changed');await api(`/api/tenants/${tenantId}/piq/target-profiles/${w.profile.id}`,{method:'DELETE'});save({profileId:null,runId:null});close();ctx.navigate('piq');}catch(err){toast(err.message,'error');e.target.disabled=false;}})}));
  $('#piq-profile-select',box).addEventListener('change',e=>{save({profileId:e.target.value,runId:null});ctx.navigate('piq');});
  $('#piq-pull-profile-select',box).addEventListener('change',e=>{save({profileId:e.target.value,runId:null});ctx.navigate('piq');});
  $('#piq-latest-pull',box).addEventListener('click',()=>{if(w.runs[0]){save({runId:w.runs[0].run_id});ctx.navigate('piq');}});
  $('#piq-all-leads',box).addEventListener('click',()=>{save({runId:'all'});ctx.navigate('piq');});
  $('#piq-run-select',box).addEventListener('change',e=>{save({runId:e.target.value});ctx.navigate('piq');});
  $('#piq-show-archived',box).addEventListener('change',e=>{save({archived:e.target.checked});ctx.navigate('piq');});
  const count=()=>quantity($('#piq-quantity',box).value==='custom'?$('#piq-custom-quantity',box).value:$('#piq-quantity',box).value,max);
  const changed=()=>{$('#piq-custom-wrap',box).hidden=$('#piq-quantity',box).value!=='custom';try{const value=count();save({quantity:value});$('#piq-quantity-help',box).textContent=`Pull up to ${value} new discovered prospects. Fewer may be available within the search limits.`;}catch(e){$('#piq-quantity-help',box).textContent=e.message;}};
  $('#piq-quantity',box).addEventListener('change',changed);$('#piq-custom-quantity',box).addEventListener('input',changed);
  if(button&&!editable)button.remove();
  if(button&&(!w.profile||!w.profile.active))button.disabled=true;
  return {profileId:w.profile?.id,requestedCount:count,enabled:editable&&!!w.profile?.active,onRun:run=>{save({runId:run.run_id});const el=$('[data-piq-run-summary]',box);if(el)el.textContent=runSummary(run);}};
}
export function applyResearchState(page,rows){
  for(const row of rows){
    const research=row.research;if(!research)continue;
    const button=page.querySelector(`[data-research-piq="${row.id}"]`);
    if(button && !research.eligible){button.disabled=true;button.title=research.reason;}
    const card=page.querySelector(`[data-open-piq="${row.id}"],[data-piq-profile="${row.id}"]`)?.closest('article,tr');
    if(card){const notice=document.createElement('p');notice.dataset.researchOutcome=row.id;notice.textContent=research.latest?researchMessage(research.latest):research.reason||'Research not yet run.';(card.tagName==='TR'?card.querySelector('td'):card).append(notice);}
  }
}
