import {api} from '../api.js';
import {state} from '../state.js';
import {toast} from '../ui.js';

export async function attachProspectiqLaunch(page, tenantId) {
  try {
    const availability = await api('/api/integrations/prospectiq/v1/availability?tenant_id=' + encodeURIComponent(tenantId));
    if (!availability.enabled || state.selectedTenantId !== tenantId || !page.isConnected) return;
    const card = document.createElement('section');
    card.className = 'card';
    const button = document.createElement('button');
    button.className = 'button secondary';
    button.textContent = 'Open ProspectIQ';
    card.append(button);
    page.prepend(card);
    button.addEventListener('click', async () => {
      if (state.selectedTenantId !== tenantId) return;
      button.disabled = true;
      try {
        const result = await api('/api/integrations/prospectiq/v1/launch', {
          method:'POST', body:{mapping_id:availability.mapping_id, destination:'prospects'},
        });
        const url = new URL(result.launch_url);
        if (url.protocol !== 'https:') throw new Error('Secure ProspectIQ destination required');
        // Same tab avoids popup blocking and carries no opener relationship.
        location.assign(url.href);
      } catch (error) { toast(error.message, 'error'); button.disabled = false; }
    });
  } catch { /* Disabled, unconfigured or unauthorized: native PIQ remains intact. */ }
}
