import {api} from './api.js';
import {state, isGlobalAdmin} from './state.js';
import {$, applyFieldErrors, bindGlobalUI, esc, modal, renderShell, toast, updateBackButton} from './ui.js';
import {renderAdminPage} from './pages/admin.js';
import {renderClientPage} from './pages/client.js';
import {renderUnifiedPage} from './pages/unified.js';
import {refreshTenantTheme as loadTenantTheme, clearTenantTheme, applyTenantTheme} from './tenant-theme.js';

const CLIENT_ROUTES = new Set(['home','crm','forecast','reports','piq','solutions','campaigns','email','website','organization','training']);
const UNIFIED_ROUTES = new Set(['home','crm','forecast','reports','piq','solutions','campaigns','email','website','organization','training']);
const CLIENT_OPERATION_ROUTES = new Set(['crm','forecast','reports','piq','campaigns','website','organization']);

window.addEventListener('rmr:unauthorized', () => { state.user = null; renderLogin('Your session ended. Please sign in again.'); });
window.addEventListener('hashchange', renderRoute);

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, '');
  const [routePart='', queryPart=''] = raw.split('?');
  const route = routePart.split('/')[0] || (state.user && isGlobalAdmin() ? 'portfolio' : 'home');
  const query = Object.fromEntries(new URLSearchParams(queryPart));
  return {route, query};
}

async function boot() {
  const special = parseHash();
  try {
    const setup = await api('/api/setup/status');
    if (setup.setup_required) { renderInitialSetup(); return; }
  } catch (_) {}
  if (special.route === 'activate' && location.hash.includes('/activate/')) {
    renderInvitationActivation(location.hash.split('/activate/')[1].split('?')[0]); return;
  }
  if (special.route === 'reset-password' && location.hash.includes('/reset-password/')) {
    renderPasswordReset(location.hash.split('/reset-password/')[1].split('?')[0]); return;
  }
  try {
    const {user} = await api('/api/auth/me');
    await enterApp(user, false);
  } catch (_) {
    renderLogin();
  }
}

async function enterApp(user, navigateHome=true) {
  state.user = user;
  if (user.must_change_password) { renderPasswordChange(); return; }
  await refreshTenants();
  if (isGlobalAdmin()) {
    const saved = localStorage.getItem('rmr_selected_tenant');
    state.selectedTenantId = state.tenants.some(t=>t.id===saved) ? saved : null;
  } else {
    state.selectedTenantId = user.tenant_id;
  }
  await refreshModules();
  await loadTenantTheme();
  renderShell();
  bindGlobalUI({navigate, goBack, logout, onTenantChange:selectTenant, showNotifications});
  bindWorkspaceControls();
  if (navigateHome || !location.hash || ['activate','reset-password'].includes(parseHash().route)) {
    navigate(isGlobalAdmin() ? 'portfolio' : 'home', false);
  }
  await renderRoute();
}

async function refreshTenants({refreshShell=false}={}) {
  const data = await api('/api/tenants');
  state.tenants = data.tenants;
  if (!state.selectedTenantId || !state.tenants.some(t => t.id === state.selectedTenantId)) {
    state.selectedTenantId = isGlobalAdmin() ? null : (state.user?.tenant_id || null);
  }
  if (refreshShell && state.user) {
    await refreshModules();
    await loadTenantTheme();
    renderShell();
    bindGlobalUI({navigate, goBack, logout, onTenantChange:selectTenant, showNotifications});
    bindWorkspaceControls();
  }
}

async function selectTenant(tenantId) {
  state.selectedTenantId = tenantId || null;
  state.adminClientWorkspace = false;
  state.managedSession = null;
  sessionStorage.removeItem('rmr_managed_session');
  if (tenantId) localStorage.setItem('rmr_selected_tenant', tenantId);
  else localStorage.removeItem('rmr_selected_tenant');
  await refreshModules();
  await loadTenantTheme();
  renderShell();
  bindGlobalUI({navigate, goBack, logout, onTenantChange:selectTenant, showNotifications});
  bindWorkspaceControls();
  if (isGlobalAdmin() && tenantId) navigate(`client-360?tenant=${encodeURIComponent(tenantId)}`);
  else renderRoute();
}

async function refreshModules() {
  state.modules = []; state.moduleServices = [];
  if (!state.selectedTenantId) return;
  try {
    const data = await api(`/api/tenants/${state.selectedTenantId}/modules`);
    state.modules = data.modules || []; state.moduleServices = data.services || [];
  } catch (_) {}
}

async function refreshTenantTheme({rerender=false, tenantId=null}={}) {
  if (tenantId && tenantId !== state.selectedTenantId) {
    state.selectedTenantId = tenantId;
    localStorage.setItem('rmr_selected_tenant', tenantId);
  }
  await loadTenantTheme();
  if (rerender && state.user) {
    renderShell();
    bindGlobalUI({navigate, goBack, logout, onTenantChange:selectTenant, showNotifications});
    bindWorkspaceControls();
    await renderRoute();
  }
  return state.tenantTheme;
}

function navigate(route, push=true) {
  const hash = `#/${route}`;
  if (location.hash === hash) renderRoute();
  else if (push) location.hash = hash;
  else history.replaceState(null, '', hash);
}

function goBack() {
  if (history.length > 1) history.back();
  else navigate(isGlobalAdmin() ? 'portfolio' : 'home');
}

async function renderRoute() {
  if (!state.user) return;
  const {route, query} = parseHash();
  state.route = route;
  state.routeQuery = query;
  let routeTenantChanged = false;
  if (query.tenant && state.tenants.some(t=>t.id===query.tenant)) {
    routeTenantChanged = query.tenant !== state.selectedTenantId;
    state.selectedTenantId = query.tenant;
    localStorage.setItem('rmr_selected_tenant', query.tenant);
    const selector = $('#tenant-selector'); if (selector) selector.value = query.tenant;
  }
  if (routeTenantChanged) {
    await refreshModules();
    await loadTenantTheme();
  } else {
    applyTenantTheme();
  }
  updateBackButton(!['portfolio','home'].includes(route));
  const ctx = {
    navigate,
    goBack,
    refreshTenants,
    selectTenant,
    enterClientWorkspace,
    exitClientWorkspace,
    refreshTenantTheme,
    renderClientOperational: (clientRoute, readOnly) => renderClientPage(clientRoute, ctx, readOnly)
  };
  if (isGlobalAdmin()) {
    if (state.adminClientWorkspace) {
      const clientRoute = CLIENT_ROUTES.has(route) ? route : 'home';
      return UNIFIED_ROUTES.has(clientRoute) ? renderUnifiedPage(clientRoute, ctx, !state.managedSession) : renderClientPage(clientRoute, ctx, !state.managedSession);
    }
    if (CLIENT_OPERATION_ROUTES.has(route)) return renderClientPage(route, ctx, true);
    return renderAdminPage(route, ctx);
  }
  const clientRoute = CLIENT_ROUTES.has(route) ? route : 'home';
  return UNIFIED_ROUTES.has(clientRoute) ? renderUnifiedPage(clientRoute, ctx, false) : renderClientPage(clientRoute, ctx, false);
}

async function enterClientWorkspace(tenantId=state.selectedTenantId) {
  if (!tenantId) { toast('Select a client first','error'); return; }
  state.selectedTenantId = tenantId;
  localStorage.setItem('rmr_selected_tenant', tenantId);
  state.adminClientWorkspace = true;
  await refreshModules();
  await loadTenantTheme();
  try {
    const current = await api('/api/managed-session/current');
    if (current.session?.tenant_id === tenantId) {
      state.managedSession = current.session;
      sessionStorage.setItem('rmr_managed_session', current.session.id);
    }
  } catch (_) {}
  renderShell();
  bindGlobalUI({navigate, goBack, logout, onTenantChange:selectTenant, showNotifications});
  bindWorkspaceControls();
  navigate('home');
}

async function exitClientWorkspace() {
  if (state.managedSession) {
    try { await api(`/api/managed-session/${state.managedSession.id}/end`, {method:'POST', body:{}}); } catch (_) {}
  }
  state.managedSession = null; state.adminClientWorkspace = false; state.modules=[];
  sessionStorage.removeItem('rmr_managed_session');
  renderShell();
  bindGlobalUI({navigate, goBack, logout, onTenantChange:selectTenant, showNotifications});
  bindWorkspaceControls();
  navigate(`client-360?tenant=${encodeURIComponent(state.selectedTenantId||'')}`);
}

function bindWorkspaceControls() {
  $('#exit-client-workspace')?.addEventListener('click', exitClientWorkspace);
  $('#start-managed-session')?.addEventListener('click', () => {
    modal({title:'Start authorized client workspace session',body:`<p>This session allows RMR/Step2 to perform authorized managed services inside the selected client tenant. Every action remains attributed to your own administrator identity and is written to the audit history.</p><div class="field"><label>Reason for access</label><textarea id="managed-reason" style="min-height:100px">Product demonstration and authorized RMR managed services</textarea></div>`,footer:'<button class="button secondary" data-close-modal>Cancel</button><button class="button" id="confirm-managed-session">Start session</button>',onOpen:(root,close)=>$('#confirm-managed-session',root).addEventListener('click',async()=>{try{const result=await api(`/api/tenants/${state.selectedTenantId}/managed-session`,{method:'POST',body:{reason:$('#managed-reason',root).value,minutes:120}});state.managedSession=result.session;sessionStorage.setItem('rmr_managed_session',result.session.id);close();renderShell();bindGlobalUI({navigate,goBack,logout,onTenantChange:selectTenant,showNotifications});bindWorkspaceControls();renderRoute();toast('Authorized client workspace session started')}catch(e){toast(e.message,'error')}})});
  });
  $('#end-managed-session')?.addEventListener('click', async()=>{try{await api(`/api/managed-session/${state.managedSession.id}/end`,{method:'POST',body:{}})}catch(_){}state.managedSession=null;sessionStorage.removeItem('rmr_managed_session');renderShell();bindGlobalUI({navigate,goBack,logout,onTenantChange:selectTenant,showNotifications});bindWorkspaceControls();renderRoute();toast('Managed session ended')});
}

async function logout() {
  try { await api('/api/auth/logout', {method:'POST', body:{}}); } catch (_) {}
  state.user = null; state.tenants = []; state.selectedTenantId = null;
  localStorage.removeItem('rmr_selected_tenant');
  sessionStorage.removeItem('rmr_managed_session');
  state.modules=[]; state.moduleServices=[]; state.adminClientWorkspace=false; state.managedSession=null;
  clearTenantTheme();
  renderLogin();
}

async function showNotifications() {
  try {
    const data = await api('/api/notifications');
    modal({
      title:'Notifications',
      body:data.notifications.length ? `<div class="grid">${data.notifications.map(n=>`<button class="list-item" data-notification="${n.id}" data-action-route="${esc(n.action_route||'')}" style="text-align:left"><span class="grow"><strong>${esc(n.title)}</strong><small class="muted">${esc(n.body)} · ${new Date(n.created_at).toLocaleString()}</small></span>${n.status==='unread'?'<span class="badge purple">New</span>':''}${n.action_route?`<span class="tiny">${esc(n.action_label||'Open')} →</span>`:''}</button>`).join('')}</div>` : '<div class="empty-state"><strong>No notifications</strong><span>You are caught up.</span></div>',
      footer:'<button class="button secondary" data-close-modal>Close</button>',
      onOpen:(root,close)=>root.querySelectorAll('[data-notification]').forEach(btn=>btn.addEventListener('click',async()=>{
        const result=await api(`/api/notifications/${btn.dataset.notification}/read`,{method:'PATCH',body:{}});
        const action=btn.dataset.actionRoute || result.action_route;
        if (action) { close(); navigate(action); }
        else btn.querySelector('.badge')?.remove();
      }))
    });
  } catch (error) { toast(error.message,'error'); }
}

function authShell(formHtml, eyebrow, title, text) {
  return `<div class="login-shell auth-wide"><section class="login-panel"><div class="login-card"><div class="brand-mark" style="margin-bottom:24px">R</div>${formHtml}</div></section><section class="login-visual"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p>${text}</p></div></section></div>`;
}

function renderInitialSetup() {
  document.querySelector('#app').innerHTML = authShell(`<form class="login-form setup-form" id="setup-form"><h2>Complete initial setup</h2><p class="subtle">Create the RMR owner account and, if desired, the Step2 platform administrator. Successful setup signs the RMR owner in automatically.</p><div class="form-grid"><div class="field full"><label>Installation token</label><input name="setup_token" type="password" required autocomplete="off"></div><div class="field"><label>RMR owner name</label><input name="owner_name" required value="Dave Laughlin"></div><div class="field"><label>RMR owner email</label><input name="owner_email" type="email" required></div><div class="field"><label>RMR owner password</label><input name="owner_password" type="password" minlength="12" required autocomplete="new-password"></div><div class="field"><label>Confirm RMR owner password</label><input name="owner_confirm" type="password" minlength="12" required></div><label class="list-item full"><input name="create_step2_admin" type="checkbox"><span>Create Step2 platform administrator now</span></label><div class="field step2-field"><label>Step2 administrator name</label><input name="step2_name" value="Hasan — Step2"></div><div class="field step2-field"><label>Step2 administrator email</label><input name="step2_email" type="email"></div><div class="field step2-field"><label>Step2 administrator password</label><input name="step2_password" type="password" minlength="12" autocomplete="new-password"></div><div class="field step2-field"><label>Confirm Step2 password</label><input name="step2_confirm" type="password" minlength="12"></div></div><button class="button" type="submit">Complete setup</button></form>`, 'FIRST-RUN SETUP', 'Install once. Operate from the browser.', 'The installer prepares the application. This guided setup creates the initial administrative access and verifies it before continuing.');
  const form=$('#setup-form');
  const toggle=()=>form.querySelectorAll('.step2-field').forEach(el=>el.hidden=!form.create_step2_admin.checked);
  form.create_step2_admin.addEventListener('change',toggle); toggle();
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    if(form.owner_password.value!==form.owner_confirm.value){toast('RMR owner passwords do not match','error');return;}
    if(form.create_step2_admin.checked && form.step2_password.value!==form.step2_confirm.value){toast('Step2 passwords do not match','error');return;}
    const btn=form.querySelector('button[type=submit]');btn.disabled=true;btn.textContent='Completing setup…';
    try{
      const result=await api('/api/setup/complete',{method:'POST',body:{setup_token:form.setup_token.value,owner_name:form.owner_name.value,owner_email:form.owner_email.value,owner_password:form.owner_password.value,create_step2_admin:form.create_step2_admin.checked,step2_name:form.step2_name.value,step2_email:form.step2_email.value,step2_password:form.step2_password.value}});
      toast('Initial setup complete'); await enterApp(result.user,true);
    }catch(error){applyFieldErrors(form,error.fieldErrors);toast(error.message,'error');btn.disabled=false;btn.textContent='Complete setup';}
  });
}

function renderPasswordChange(){
  document.querySelector('#app').innerHTML=authShell(`<form class="login-form" id="password-form"><h2>Choose a new password</h2><p class="subtle">Use a unique password of at least 12 characters.</p><div class="field"><label>Current password</label><input name="current_password" type="password" required autocomplete="current-password"></div><div class="field"><label>New password</label><input name="new_password" type="password" minlength="12" required autocomplete="new-password"></div><div class="field"><label>Confirm new password</label><input name="confirm_password" type="password" minlength="12" required autocomplete="new-password"></div><button class="button" type="submit">Save new password</button><button class="button secondary" type="button" id="password-logout">Sign out</button></form>`, 'ACCOUNT SECURITY', 'Protect client and platform information.', 'Your password is private. RMR and Step2 administrators cannot view it.');
  $('#password-logout').addEventListener('click',logout);
  $('#password-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;if(form.new_password.value!==form.confirm_password.value){toast('New passwords do not match','error');return;}const btn=form.querySelector('button[type=submit]');btn.disabled=true;try{const result=await api('/api/auth/change-password',{method:'POST',body:{current_password:form.current_password.value,new_password:form.new_password.value}});await enterApp(result.user,true);toast('Password updated')}catch(error){toast(error.message,'error');btn.disabled=false;}});
}

async function renderLogin(message='') {
  let demos=[];try{demos=(await api('/api/auth/demo-users')).users}catch(_){}
  document.querySelector('#app').innerHTML=authShell(`<form class="login-form" id="login-form"><h2>Sign in to RMR Global</h2><p class="subtle">Secure access for RMR, Step2, and authorized client users.</p>${message?`<div class="readonly-banner">${esc(message)}</div>`:''}<div class="field"><label>Email</label><input name="email" type="email" required autocomplete="username"></div><div class="field"><label>Password</label><input name="password" type="password" required autocomplete="current-password"></div><button class="button" type="submit">Sign in</button><button class="text-button" type="button" id="forgot-password">Forgot password?</button></form>${demos.length?`<div class="demo-logins"><div class="nav-label" style="padding-left:0">Pilot demo accounts</div>${demos.map(d=>`<button class="demo-login" data-demo-email="${esc(d.email)}" data-demo-password="${esc(d.password)}"><span><strong>${esc(d.label)}</strong><small class="muted">${esc(d.email)}</small></span><span>Use</span></button>`).join('')}</div>`:''}`, 'RMR GLOBAL PRODUCT OWNER CANDIDATE', 'Your website, prospects, customers and growth—in one place.', 'One multi-tenant platform for client operations, managed services and accountable growth.');
  $('#forgot-password').addEventListener('click',renderForgotPassword);
  $('#login-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;const submit=form.querySelector('button[type=submit]');submit.disabled=true;submit.textContent='Signing in…';try{const result=await api('/api/auth/login',{method:'POST',body:{email:form.email.value,password:form.password.value}});await enterApp(result.user,true)}catch(error){toast(error.message,'error');submit.disabled=false;submit.textContent='Sign in';}});
  document.querySelectorAll('[data-demo-email]').forEach(btn=>btn.addEventListener('click',()=>{const form=$('#login-form');form.email.value=btn.dataset.demoEmail;form.password.value=btn.dataset.demoPassword;form.requestSubmit()}));
}

function renderForgotPassword(){
  document.querySelector('#app').innerHTML=authShell(`<form class="login-form" id="forgot-form"><h2>Reset your password</h2><p class="subtle">Enter your account email. Pilot installations provide a one-time local reset link; production installations send the secure link by email.</p><div class="field"><label>Email</label><input name="email" type="email" required></div><button class="button" type="submit">Create reset link</button><button class="button secondary" type="button" id="back-login">Back to sign in</button></form>`, 'ACCOUNT RECOVERY', 'Recover access securely.', 'One-time reset links expire and cannot be reused.');
  $('#back-login').addEventListener('click',()=>renderLogin());
  $('#forgot-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;try{const result=await api('/api/auth/password-reset/request',{method:'POST',body:{email:form.email.value}});if(result.reset_url){modal({title:'Password reset link created',body:`<p>${esc(result.message)}</p><div class="secure-link"><code>${esc(result.reset_url)}</code><button class="button secondary small" id="open-reset">Open</button></div>`,footer:'<button class="button secondary" data-close-modal>Close</button>',onOpen:(root,close)=>$('#open-reset',root).addEventListener('click',()=>{close();location.hash=result.reset_url.split('/#')[1]||result.reset_url;})});}else{toast(result.message);renderLogin('Check your email for the reset link.');}}catch(error){toast(error.message,'error')}});
}

async function renderInvitationActivation(token){
  try{
    const data=await api(`/api/auth/invitations/${encodeURIComponent(token)}`);
    document.querySelector('#app').innerHTML=authShell(`<form class="login-form" id="activation-form"><h2>Activate your ${esc(data.tenant.name)} account</h2><p class="subtle">Welcome ${esc(data.invitation.full_name)}. Create your private password to enter your organization’s tenant.</p><div class="field"><label>Email</label><input value="${esc(data.invitation.email)}" disabled></div><div class="field"><label>Role</label><input value="${esc(data.invitation.tenant_role.replaceAll('_',' '))}" disabled></div><div class="field"><label>Password</label><input name="password" type="password" minlength="12" required></div><div class="field"><label>Confirm password</label><input name="confirm" type="password" minlength="12" required></div><button class="button" type="submit">Activate account</button></form>`, 'CLIENT ACCESS', `Welcome to ${esc(data.tenant.name)}.`, 'Your account is isolated to your organization and the services it has been authorized to use.');
    $('#activation-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;if(form.password.value!==form.confirm.value){toast('Passwords do not match','error');return;}try{const result=await api('/api/auth/invitations/accept',{method:'POST',body:{token,password:form.password.value}});toast('Account activated');await enterApp(result.user,true)}catch(error){toast(error.message,'error')}});
  }catch(error){renderLogin(error.message)}
}

function renderPasswordReset(token){
  document.querySelector('#app').innerHTML=authShell(`<form class="login-form" id="reset-form"><h2>Choose a new password</h2><p class="subtle">This one-time recovery link expires and can be used only once.</p><div class="field"><label>New password</label><input name="password" type="password" minlength="12" required></div><div class="field"><label>Confirm password</label><input name="confirm" type="password" minlength="12" required></div><button class="button" type="submit">Reset password</button></form>`, 'ACCOUNT RECOVERY', 'Return to work securely.', 'A successful reset signs you in automatically.');
  $('#reset-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;if(form.password.value!==form.confirm.value){toast('Passwords do not match','error');return;}try{const result=await api('/api/auth/password-reset/complete',{method:'POST',body:{token,new_password:form.password.value}});toast('Password reset complete');await enterApp(result.user,true)}catch(error){toast(error.message,'error')}});
}

boot();
