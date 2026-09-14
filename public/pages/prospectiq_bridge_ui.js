import {api} from '../api.js';
import {state} from '../state.js';
import {esc, toast} from '../ui.js';

// Return false ONLY when the server explicitly reports native mode.
// Bridge failures must not expose a second set of prospecting controls.
export async function renderProspectiqBridge(page, tenantId) {
  const current = () => state.selectedTenantId === tenantId && state.route === 'piq' && page.isConnected;
  try {
    let availability = await api('/api/integrations/prospectiq/v1/availability?tenant_id=' + encodeURIComponent(tenantId));
    if (!current()) return true;
    if (availability.enabled === false) return false;
    if (availability.enabled === true && availability.status === 'unprovisioned') {
      if (!availability.can_provision) {
        page.innerHTML = '<section class="card" data-piq-bridge-unavailable><h1>ProspectIQ</h1><p>Ask a client administrator to prepare this workspace before continuing.</p></section>';
        return true;
      }
      page.innerHTML = '<section class="card" data-piq-bridge-preparing><h1>ProspectIQ</h1><p role="status">Preparing ProspectIQ…</p></section>';
      try {
        const prepared = await api('/api/integrations/prospectiq/v1/provision', {method:'POST',body:{tenant_id:tenantId}});
        if (!current()) return true;
        if (prepared.status !== 'ready' || !prepared.mapping_id) throw new Error('Preparation incomplete');
        availability = {enabled:true,mapping_id:prepared.mapping_id};
      } catch {
        if (current()) {
          page.innerHTML = '<section class="card" data-piq-bridge-unavailable><h1>ProspectIQ</h1><p>ProspectIQ could not be prepared. Retry shortly or contact your administrator if the problem persists.</p><button class="button" data-retry-prospectiq>Retry preparation</button></section>';
          page.querySelector('[data-retry-prospectiq]').addEventListener('click', () => { if (current()) renderProspectiqBridge(page,tenantId); });
        }
        return true;
      }
    }
    if (availability.enabled !== true || !availability.mapping_id) throw new Error('ProspectIQ mapping unavailable');
    page.innerHTML = '<section class="card"><h1>ProspectIQ</h1><p role="status">Preparing initial Target Profiles…</p></section>';
    try {
      const bootstrap = await api('/api/integrations/prospectiq/v1/profiles/bootstrap', {method:'POST',body:{tenant_id:tenantId}});
      if (!current()) return true;
      if (bootstrap.status !== 'completed') throw new Error('Preparation incomplete');
    } catch {
      if (current()) {
        page.innerHTML = '<section class="card" data-piq-bridge-unavailable><h1>ProspectIQ</h1><p>Initial Target Profiles could not be prepared. An operational user must complete first-use preparation. Retry or contact your administrator.</p><button class="button" data-retry-prospectiq>Retry preparation</button></section>';
        page.querySelector('[data-retry-prospectiq]').addEventListener('click', () => { if (current()) renderProspectiqBridge(page,tenantId); });
      }
      return true;
    }
    renderHistoryLauncher(page,tenantId,availability.mapping_id,current);
    return true;
  } catch {
    if (current()) page.innerHTML = '<section class="card" data-piq-bridge-unavailable><h1>ProspectIQ</h1><p>ProspectIQ access is temporarily unavailable or not authorized for this workspace. Contact your administrator or reload to retry.</p></section>';
    return true;
  }
}

function renderHistoryLauncher(page,tenantId,mappingId,current) {
  const pending=new Set();
  let history=false,historyGeneration=0;
  const launch=async(button,destination)=>{
    if(!current() || button.disabled)return;
    button.disabled=true;
    try {
      const result=await api('/api/integrations/prospectiq/v1/launch',{method:'POST',body:{mapping_id:mappingId,destination}});
      const url=new URL(result.launch_url);
      if(url.protocol!=='https:')throw Error('Secure ProspectIQ destination required');
      if(current())location.assign(url.href);
    }catch(error){if(current())toast(error.message,'error');button.disabled=false;}
  };
  const draw=()=>{
    if(!current())return;
    page.innerHTML=`<section class="card" data-piq-bridge-launcher><h1>ProspectIQ</h1>
      <nav class="actions" aria-label="ProspectIQ sections">
        <button class="button ${history?'secondary':''}" data-piq-main aria-pressed="${!history}">ProspectIQ</button>
        <button class="button ${history?'':'secondary'}" data-piq-history aria-pressed="${history}">Previous RMR Profiles</button>
      </nav>
      ${history?'<button class="button secondary" data-open-prospectiq>Open ProspectIQ</button><div data-piq-history-content><p role="status">Loading previous RMR profiles...</p></div>':
        '<p>Create and manage Target Profiles, leads and research in ProspectIQ. Your workspace is ready.</p><button class="button" data-open-prospectiq>Open ProspectIQ</button>'}
    </section>`;
    page.querySelector('[data-piq-main]').addEventListener('click',()=>{history=false;historyGeneration++;draw();});
    page.querySelector('[data-piq-history]').addEventListener('click',()=>{history=true;draw();loadHistory();});
    const b=page.querySelector('[data-open-prospectiq]');b.addEventListener('click',()=>launch(b,history?'target_profiles':'prospects'));
  };
  const loadHistory=async()=>{
    const generation=++historyGeneration;
    try{
      const result=await api(`/api/tenants/${tenantId}/piq/target-profiles?include_archived=true`);
      if(!current() || !history || generation!==historyGeneration)return;
      const host=page.querySelector('[data-piq-history-content]');
      host.innerHTML='<h2>Previous RMR Profiles</h2><p>Historical RMR source records only. These may no longer exist in ProspectIQ and are not automatically synchronized.</p>'+
        (result.profiles||[]).map(p=>`<article class="notice-card" data-piq-source-profile="${esc(p.id)}"><h3>${esc(p.name)}</h3>
          <p>Historical RMR source. Kept for reference, not a current ProspectIQ profile.</p>
          <p>${esc((p.industries_json||[]).join(', '))} &middot; ${esc((p.locations_json||[]).join(' / '))}</p>
          <button class="button secondary" data-copy-profile="${esc(p.id)}">Create New PIQ Profile From This</button>
          <div data-copy-result="${esc(p.id)}" role="status"></div></article>`).join('');
      if(!result.profiles?.length)host.innerHTML+='<p>No previous RMR profiles.</p>';
      for(const button of host.querySelectorAll('[data-copy-profile]')){
        button.disabled=pending.has(button.dataset.copyProfile);
        button.addEventListener('click',async()=>{
          const id=button.dataset.copyProfile;
          if(!current() || pending.has(id))return;
          const key='rmr-history-copy:'+tenantId+':'+id;
          pending.add(id);button.disabled=true;
          try{
            let action=JSON.parse(localStorage.getItem(key)||'null');
            if(action?.completed){
              if(!confirm('A copy was already created. Create another new PIQ profile?'))return;
              action=null;
            }
            if(!action){action={request_id:crypto.randomUUID()};localStorage.setItem(key,JSON.stringify(action));}
            const copied=await api('/api/integrations/prospectiq/v1/profiles/history-copy',{
              method:'POST',body:{source_profile_id:id,request_id:action.request_id}});
            action.completed=true;localStorage.setItem(key,JSON.stringify(action));
            if(!current() || !history || generation!==historyGeneration)return;
            const status=host.querySelector(`[data-copy-result="${id}"]`);
            status.innerHTML=copied.status==='deleted'?'<p>This copy was already created and later deleted in ProspectIQ. It has not been restored.</p>':
              `<p>New PIQ profile created. ${copied.status==='draft'?'Complete the copied draft in ProspectIQ and activate it before pulling leads.':'Manage this separate copy in ProspectIQ.'}</p><button class="button" data-open-copy>Open PIQ Target Profiles</button>`;
            const open=status.querySelector('[data-open-copy]');
            if(open)open.addEventListener('click',()=>launch(open,'target_profiles'));
            button.textContent='Create another new PIQ profile';
          }catch(error){if(current())toast(error.message,'error');}
          finally{pending.delete(id);button.disabled=false;}
        });
      }
    }catch{if(current() && history && generation===historyGeneration)page.querySelector('[data-piq-history-content]').innerHTML='<p>Previous RMR profiles are temporarily unavailable. Reopen this section to retry.</p>';}
  };
  draw();
}
