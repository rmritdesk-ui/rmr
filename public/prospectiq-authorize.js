// Same-origin landing restores Strict-cookie eligibility without weakening cookies.
const params = new URLSearchParams(location.hash.slice(1));
history.replaceState(null, '', location.pathname);
const body = Object.fromEntries(['transaction_id','callback_id','state','nonce','code_challenge','code_challenge_method']
  .map(key => [key, params.get(key)]));
(async () => {
  try {
    const response = await fetch('/api/integrations/prospectiq/v1/authorize', {
      method:'POST', credentials:'same-origin',
      headers:{'Content-Type':'application/json','X-RMR-Request':'1'}, body:JSON.stringify(body),
    });
    if (!response.ok) throw new Error('Launch expired or unavailable. Return to RMR and open ProspectIQ again.');
    const data = await response.json();
    // Only the authenticated same-origin RMR server supplies this destination.
    const callback = new URL(data.callback_url);
    if (callback.protocol !== 'https:') throw new Error('Secure callback required.');
    location.replace(callback.href);
  } catch (error) {
    document.getElementById('bridge-message').textContent = error.message;
    document.getElementById('bridge-return').hidden = false;
  }
})();
