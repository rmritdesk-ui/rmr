import {api} from '../api.js';
import {state} from '../state.js';
import {toast} from '../ui.js';

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
    renderLauncher(page,availability.mapping_id,current);
    return true;
  } catch {
    if (current()) page.innerHTML = '<section class="card" data-piq-bridge-unavailable><h1>ProspectIQ</h1><p>ProspectIQ access is temporarily unavailable or not authorized for this workspace. Contact your administrator or reload to retry.</p></section>';
    return true;
  }
}

function renderLauncher(page,mappingId,current) {
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
  if(!current())return;
  page.innerHTML=`<section class="card" data-piq-bridge-launcher><h1>ProspectIQ</h1>
    <p>Create and manage Target Profiles, leads and research in ProspectIQ. Your workspace is ready.</p>
    <button class="button" data-open-prospectiq>Open ProspectIQ</button>
  </section>`;
  const b=page.querySelector('[data-open-prospectiq]');
  b.addEventListener('click',()=>launch(b,'prospects'));
}
