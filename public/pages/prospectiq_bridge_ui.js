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
    let profiles = [];
    let summaryUnavailable = false;
    try {
      const collection = await api(`/api/tenants/${tenantId}/piq/target-profiles?include_archived=true`);
      profiles = collection.profiles || [];
    } catch { summaryUnavailable = true; }
    if (!current()) return true;
    page.innerHTML = `<section class="card" data-piq-bridge-launcher>
      <div class="card-head"><div><h1>ProspectIQ</h1><p>Target Profiles, prospecting, scoring, research and CRM handoff are managed in ProspectIQ.</p></div></div>
      <h2>Target Profile transition</h2>
      ${profiles.map(profile => `<article class="notice-card" data-piq-source-profile="${esc(profile.id)}"><h3>${esc(profile.name)}</h3>
        <p>Preserved RMR source: ${profile.active ? 'Active' : 'Archived'}. Current profile status and editing are managed in ProspectIQ.</p>
        <p>${esc((profile.industries_json || []).join(', '))} · ${esc((profile.locations_json || []).join(' / '))}</p></article>`).join('')}
      ${profiles.length ? '<p>These are preserved RMR source profiles. Profile import is a separate transition step; continue to ProspectIQ to view the profiles available there.</p>' : `<p>${summaryUnavailable ? 'The RMR source profile summary is temporarily unavailable.' : 'Create and manage your Target Profiles in ProspectIQ.'}</p>`}
      <button class="button" data-open-prospectiq>Open ProspectIQ</button>
    </section>`;
    const button = page.querySelector('[data-open-prospectiq]');
    button.addEventListener('click', async () => {
      if (!current()) return;
      button.disabled = true;
      try {
        const result = await api('/api/integrations/prospectiq/v1/launch', {
          method:'POST', body:{mapping_id:availability.mapping_id, destination:'prospects'},
        });
        const url = new URL(result.launch_url);
        if (url.protocol !== 'https:') throw new Error('Secure ProspectIQ destination required');
        if (!current()) return;
        // Same tab avoids popup blocking and carries no opener relationship.
        location.assign(url.href);
      } catch (error) { toast(error.message, 'error'); button.disabled = false; }
    });
    return true;
  } catch {
    if (current()) page.innerHTML = '<section class="card" data-piq-bridge-unavailable><h1>ProspectIQ</h1><p>ProspectIQ access is temporarily unavailable or not authorized for this workspace. Contact your administrator or reload to retry.</p></section>';
    return true;
  }
}
