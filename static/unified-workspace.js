/* RMR Global v5.2 Unified Product Workspace
 * Additive customer-first surface over the preserved CB1-R2 product.
 * It never bypasses backend authorization or tenant isolation.
 */
(() => {
  'use strict';
  if (window.__RMR_UNIFIED_WORKSPACE_LOADED__) return;
  window.__RMR_UNIFIED_WORKSPACE_LOADED__ = true;

  const RELEASE = "5.4.1.2-interaction-regression-correction-po1";
  const ROUTES = {"dashboard":{"aliases":["Customer Workspace","Dashboard","Home"],"candidates":[{"route":"/activate/","score":0,"source":"public/app.js","label":"Home"},{"route":"/reset-password/","score":0,"source":"public/app.js","label":"Home"},{"route":"/sites/{site_slug}","score":-2,"source":"rmr_platform/routes/website.py","label":"Home"},{"route":"/tenants/{tenant_id}/success","score":-2,"source":"rmr_platform/routes/portfolio.py","label":"Home"},{"route":"/api/auth/me","score":-5,"source":"public/app.js","label":"Home"},{"route":"/api/tenants","score":-5,"source":"public/app.js","label":"Home"},{"route":"/api/auth/logout","score":-5,"source":"public/app.js","label":"Home"},{"route":"/api/setup/status","score":-5,"source":"public/app.js","label":"Home"}],"preferred":"/activate/"},"website":{"aliases":["Website Studio","Website"],"candidates":[{"route":"/api/website/sections/","score":5,"source":"rmr_platform/routes/website.py","label":"Website"},{"route":"/api/website/pages/{page_id}","score":3,"source":"rmr_platform/routes/website.py","label":"Website"},{"route":"/api/tenants/{tenant_id}/website","score":3,"source":"rmr_platform/routes/website.py","label":"Website"},{"route":"/api/website/sections/{section_id}","score":3,"source":"rmr_platform/routes/website.py","label":"Website"},{"route":"/api/tenants/{tenant_id}/website/pages","score":3,"source":"rmr_platform/routes/website.py","label":"Website"},{"route":"/api/tenants/{tenant_id}/website/sections","score":3,"source":"rmr_platform/routes/website.py","label":"Website"},{"route":"/api","score":0,"source":"rmr_platform/routes/portfolio.py","label":"Website"},{"route":"/static","score":0,"source":"rmr_platform/main.py","label":"Website"}],"preferred":"/api/website/sections/"},"crm":{"aliases":["CRM Workspace","CRM"],"candidates":[{"route":"/tenants/{tenant_id}/crm/summary","score":8,"source":"rmr_platform/routes/crm.py","label":"CRM"},{"route":"/piq/{opportunity_id}/move-to-crm","score":8,"source":"rmr_platform/routes/piq.py","label":"CRM"},{"route":"/api/crm","score":5,"source":"rmr_platform/commercial/middleware.py","label":"CRM"},{"route":"/api","score":0,"source":"rmr_platform/routes/crm.py","label":"CRM"},{"route":"/static","score":0,"source":"rmr_platform/main.py","label":"CRM"},{"route":"/events","score":0,"source":"rmr_platform/commercial/router.py","label":"CRM"},{"route":"/messages","score":0,"source":"templates/cb1_commercial.html","label":"CRM"},{"route":"/commercial","score":0,"source":"public/cb1_enhancements.js","label":"CRM Workspace"}],"preferred":"/tenants/{tenant_id}/crm/summary"},"piq":{"aliases":["ProspectIQ","PIQ"],"candidates":[{"route":"/tenants/{tenant_id}/piq","score":8,"source":"rmr_platform/routes/piq.py","label":"PIQ"},{"route":"/piq/{opportunity_id}/enhance","score":8,"source":"rmr_platform/routes/piq.py","label":"PIQ"},{"route":"/piq/{opportunity_id}/move-to-crm","score":8,"source":"rmr_platform/routes/piq.py","label":"PIQ"},{"route":"/api","score":0,"source":"rmr_platform/routes/piq.py","label":"ProspectIQ"},{"route":"/static","score":0,"source":"rmr_platform/main.py","label":"PIQ"},{"route":"/events","score":0,"source":"rmr_platform/commercial/router.py","label":"PIQ"},{"route":"/messages","score":0,"source":"templates/cb1_commercial.html","label":"PIQ"},{"route":"/messages/generate","score":0,"source":"templates/cb1_commercial.html","label":"PIQ"}],"preferred":"/tenants/{tenant_id}/piq"},"campaigns":{"aliases":["Campaigns & Content","Campaigns","Content"],"candidates":[{"route":"/campaigns","score":10,"source":"rmr_platform/commercial/router.py","label":"Campaigns"},{"route":"/campaigns/{campaign_id}","score":8,"source":"rmr_platform/routes/campaigns.py","label":"Campaigns"},{"route":"/campaigns/{cid}/generate","score":8,"source":"rmr_platform/commercial/router.py","label":"Campaigns"},{"route":"/tenants/{tenant_id}/campaigns","score":8,"source":"rmr_platform/routes/campaigns.py","label":"Campaigns"},{"route":"/api/cb1/tenants/{tenant_id}/campaigns","score":3,"source":"rmr_platform/cb1_router.py","label":"Campaigns"},{"route":"/api/cb1/campaigns/{campaign_id}/{action}","score":3,"source":"rmr_platform/cb1_router.py","label":"Campaigns"},{"route":"/social-content","score":2,"source":"templates/cb1_commercial.html","label":"Content"},{"route":"/me","score":0,"source":"templates/cb1_commercial.html","label":"Content"}],"preferred":"/campaigns"},"email":{"aliases":["Email & Activities","Activities","Connected Email"],"candidates":[{"route":"/tenant","score":0,"source":"rmr_platform/routes/crm.py","label":"Activities"},{"route":"/tenants/{tenant_id}/activities","score":0,"source":"rmr_platform/routes/crm.py","label":"Activities"},{"route":"/accounts/{account_id}/360","score":-2,"source":"rmr_platform/routes/crm.py","label":"Activities"},{"route":"/tenants/{tenant_id}/contacts","score":-2,"source":"rmr_platform/routes/crm.py","label":"Activities"},{"route":"/api/cb1","score":-5,"source":"templates/cb1_commercial.html","label":"Connected Email"}],"preferred":"/tenant"},"reporting":{"aliases":["Management Intelligence","Reporting","Reports","Forecasting"],"candidates":[{"route":"/tenants/{tenant_id}/reports/ttm","score":0,"source":"rmr_platform/routes/forecast.py","label":"Reports"},{"route":"/tenants/{tenant_id}/success","score":-2,"source":"rmr_platform/routes/portfolio.py","label":"Forecasting"},{"route":"/api/setup/status","score":-5,"source":"public/app.js","label":"Reports"}],"preferred":"/tenants/{tenant_id}/reports/ttm"},"training":{"aliases":["Training Library","Training"],"candidates":[{"route":"/training","score":10,"source":"rmr_platform/routes/training.py","label":"Training"},{"route":"/training/{resource_id}/progress","score":8,"source":"rmr_platform/routes/training.py","label":"Training"},{"route":"/api/training","score":5,"source":"public/pages/client.js","label":"Training Library"},{"route":"/api/training/files/{filename}","score":3,"source":"rmr_platform/main.py","label":"Training"},{"route":"/api","score":0,"source":"rmr_platform/routes/training.py","label":"Training"},{"route":"/static","score":0,"source":"rmr_platform/main.py","label":"Training"},{"route":"/{path:path}","score":-2,"source":"rmr_platform/main.py","label":"Training"},{"route":"/tenants/{tenant_id}/success","score":-2,"source":"rmr_platform/routes/portfolio.py","label":"Training"}],"preferred":"/training"},"team":{"aliases":["Sales Organization","Team","Settings"],"candidates":[{"route":"/api","score":0,"source":"rmr_platform/routes/training.py","label":"Settings"},{"route":"/audit","score":0,"source":"rmr_platform/routes/system.py","label":"Settings"},{"route":"/login","score":0,"source":"rmr_platform/routes/auth.py","label":"Settings"},{"route":"/static","score":0,"source":"rmr_platform/main.py","label":"Settings"},{"route":"/status","score":0,"source":"rmr_platform/routes/setup.py","label":"Team"},{"route":"/health","score":0,"source":"rmr_platform/routes/system.py","label":"Settings"},{"route":"/complete","score":0,"source":"rmr_platform/routes/setup.py","label":"Settings"},{"route":"/training","score":0,"source":"rmr_platform/routes/training.py","label":"Settings"}],"preferred":"/api"},"portfolio":{"aliases":["Portfolio Command Center","Return to Portfolio"],"candidates":[{"route":"/api/portfolio/summary","score":5,"source":"public/pages/admin.js","label":"Portfolio Command Center"},{"route":"/commercial#custody","score":2,"source":"public/cb1_enhancements.js","label":"Return to Portfolio"},{"route":"/commercial#access","score":0,"source":"public/cb1_enhancements.js","label":"Return to Portfolio"},{"route":"/cb1/assets/cb1.css?v=5.4.1.2-interaction-regression-correction-po1","score":0,"source":"templates/cb1_commercial.html","label":"Return to Portfolio"},{"route":"/api/cb1","score":-5,"source":"templates/cb1_commercial.html","label":"Return to Portfolio"},{"route":"/api/cb1/business-health","score":-5,"source":"public/cb1_enhancements.js","label":"Return to Portfolio"}],"preferred":"/api/portfolio/summary"},"client_access":{"aliases":["Manage Client Access","Client Access"],"candidates":[{"route":"/commercial#access","score":2,"source":"public/cb1_enhancements.js","label":"Manage Client Access"},{"route":"/readiness","score":0,"source":"public/cb1_enhancements.js","label":"Client Access"},{"route":"/commercial","score":0,"source":"public/cb1_enhancements.js","label":"Manage Client Access"},{"route":"/demo-users","score":0,"source":"rmr_platform/routes/auth.py","label":"Client Access"},{"route":"/onboarding","score":0,"source":"rmr_platform/routes/onboarding.py","label":"Client Access"},{"route":"/custody/active","score":0,"source":"public/cb1_enhancements.js","label":"Client Access"},{"route":"/commercial#custody","score":0,"source":"public/cb1_enhancements.js","label":"Manage Client Access"},{"route":"/invitations/accept","score":0,"source":"rmr_platform/routes/auth.py","label":"Client Access"}],"preferred":"/commercial#access"}};
  const MODULES = [
    {key:'dashboard',title:'Dashboard',desc:'Your website, prospects, customers, campaigns, tasks and performance in one place.',aliases:['Customer Workspace','Dashboard','Home']},
    {key:'website',title:'Website',desc:'Manage an RMR-built website or connect and monitor an external website.',aliases:['Website Studio','Website']},
    {key:'crm',title:'CRM',desc:'Accounts, leads, contacts, opportunities, activities and pipeline.',aliases:['CRM Workspace','CRM']},
    {key:'piq',title:'ProspectIQ',desc:'Find, qualify, enhance and move prospects into sales activity.',aliases:['ProspectIQ','PIQ']},
    {key:'campaigns',title:'Campaigns & Social',desc:'Campaign content, social drafts, approvals and publishing evidence.',aliases:['Campaigns & Content','Campaigns','Social Content']},
    {key:'email',title:'Email & Activities',desc:'Connected email, CRM activity, follow-up and approved sequences.',aliases:['Email & Activities','Activities','Connected Email']},
    {key:'reporting',title:'Reporting',desc:'Forecasting, management intelligence, adoption and attribution.',aliases:['Management Intelligence','Reporting','Reports','Forecasting']},
    {key:'training',title:'Training',desc:'Role-appropriate training and guided adoption.',aliases:['Training Library','Training']},
    {key:'team',title:'Team & Settings',desc:'Client administrators, users, sales organization and module settings.',aliases:['Sales Organization','Team','Settings']},
  ];
  const CLIENT_ROLES = new Set(['CLIENT_ADMIN','VP_SALES','SALES_MANAGER','SALES_REP','MARKETING_USER','EXECUTIVE_VIEWER','CLIENT_USER']);
  const ADMIN_ROLES = new Set(['RMR_OWNER','RMR_ADMIN','STEP2_ADMIN','STEP2']);
  let identity = null;
  let workspaceOpen = false;

  function textOf(el) { return (el && (el.innerText || el.textContent) || '').replace(/\s+/g,' ').trim(); }
  function norm(s) { return String(s||'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim(); }
  function findExistingControl(aliases) {
    const controls = [...document.querySelectorAll('a,button,[role="button"],[data-route],[data-page]')];
    for (const alias of aliases) {
      const n = norm(alias);
      const hit = controls.find(el => { const t=norm(textOf(el)); return t===n || t.includes(n); });
      if (hit) return hit;
    }
    return null;
  }
  function preferredRoute(key) {
    const node=ROUTES[key];
    return node && node.preferred && !String(node.preferred).startsWith('/api/') ? node.preferred : null;
  }
  function currentTenant() {
    const select=[...document.querySelectorAll('select')].find(s => /client|tenant|caf|kerry/i.test(textOf(s.parentElement)||textOf(s)));
    if (select && select.selectedOptions && select.selectedOptions[0]) return textOf(select.selectedOptions[0]);
    const heading=[...document.querySelectorAll('h1,h2,[class*="title"]')].map(textOf).find(t => /client 360|authorized client|customer/i.test(t));
    if (heading) return heading.replace(/—.*$/,'').replace(/Client 360/i,'').trim();
    return sessionStorage.getItem('rmrUnifiedTenant') || '';
  }
  function role() { return String((identity && (identity.role || identity.user_role || (identity.user&&identity.user.role))) || '').toUpperCase(); }
  function userName() { return (identity && (identity.name || identity.full_name || (identity.user&&identity.user.name) || identity.email)) || 'Authorized user'; }
  async function loadIdentity() {
    try { const r=await fetch('/api/auth/me',{credentials:'include'}); if(r.ok) identity=await r.json(); } catch (_) {}
  }
  function navigateModule(mod) {
    const existing=findExistingControl(mod.aliases);
    if(existing) { existing.click(); closeWorkspace(); return; }
    const route=preferredRoute(mod.key);
    if(route) { window.location.assign(route); return; }
    showNotice(`${mod.title} is not available for the current tenant role or entitlement.`);
  }
  function ensureStyle() {
    if(document.getElementById('rmr-unified-style')) return;
    const link=document.createElement('link'); link.id='rmr-unified-style'; link.rel='stylesheet'; link.href='/static/unified-workspace.css?v=5.4.1.2-interaction-regression-correction-po1'; document.head.appendChild(link);
  }
  function showNotice(message) {
    let n=document.getElementById('rmr-unified-notice');
    if(!n) { n=document.createElement('div'); n.id='rmr-unified-notice'; document.body.appendChild(n); }
    n.textContent=message; n.classList.add('show'); setTimeout(()=>n.classList.remove('show'),4200);
  }
  function closeWorkspace() { const el=document.getElementById('rmr-unified-overlay'); if(el) el.remove(); workspaceOpen=false; }
  function openWorkspace() {
    if(workspaceOpen) return; workspaceOpen=true; ensureStyle();
    const tenant=currentTenant(); if(tenant) sessionStorage.setItem('rmrUnifiedTenant',tenant);
    const admin=ADMIN_ROLES.has(role());
    const overlay=document.createElement('div'); overlay.id='rmr-unified-overlay';
    overlay.innerHTML=`<div class="rmr-unified-shell">
      <header class="rmr-unified-header">
        <div><div class="rmr-unified-kicker">RMR GLOBAL CUSTOMER OPERATING PLATFORM</div><h1>${tenant ? tenant+' Workspace' : 'My Business Workspace'}</h1><p>Website, prospects, customers, campaigns, communication and performance—inside one product.</p></div>
        <div class="rmr-unified-header-actions"><span class="rmr-unified-release">${RELEASE}</span><button type="button" id="rmr-unified-close">Close</button></div>
      </header>
      ${admin ? `<div class="rmr-unified-admin-banner"><strong>Authorized administrative workspace</strong><span>Acting as ${userName()}. Existing tenant permissions, attribution and audit controls remain in force.</span></div>` : ''}
      <main class="rmr-unified-grid">${MODULES.map(m=>`<button type="button" class="rmr-unified-card" data-module="${m.key}"><span class="rmr-unified-card-title">${m.title}</span><span>${m.desc}</span><small>${findExistingControl(m.aliases)||preferredRoute(m.key)?'Open module':'Not enabled for this role/tenant'}</small></button>`).join('')}</main>
      <footer class="rmr-unified-footer"><span>One tenant. One customer workspace. Modules remain governed by purchased services and role permissions.</span>${admin?'<button type="button" id="rmr-unified-portfolio">Return to RMR Portfolio</button>':''}</footer>
    </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('#rmr-unified-close').addEventListener('click',closeWorkspace);
    overlay.addEventListener('click',e=>{ if(e.target===overlay) closeWorkspace(); });
    overlay.querySelectorAll('[data-module]').forEach(btn=>btn.addEventListener('click',()=>navigateModule(MODULES.find(m=>m.key===btn.dataset.module))));
    const port=overlay.querySelector('#rmr-unified-portfolio'); if(port) port.addEventListener('click',()=>navigateModule({key:'portfolio',aliases:['Return to Portfolio','Portfolio Command Center']}));
  }
  function addLaunchControl() {
    if(document.getElementById('rmr-unified-launch')) return;
    const r=role(); const client=CLIENT_ROLES.has(r); const admin=ADMIN_ROLES.has(r);
    const tenant=currentTenant();
    if(!client && !(admin && tenant)) return;
    const b=document.createElement('button'); b.id='rmr-unified-launch'; b.type='button'; b.textContent=client?'My Business Workspace':'Open Client Workspace'; b.title='Open the unified RMR Global customer operating workspace'; b.addEventListener('click',openWorkspace); document.body.appendChild(b);
  }
  function addClient360Action() {
    if(!ADMIN_ROLES.has(role()) || document.querySelector('[data-rmr-open-client-workspace]')) return;
    const title=[...document.querySelectorAll('h1,h2')].find(el=>/client 360/i.test(textOf(el)));
    if(!title) return;
    const b=document.createElement('button'); b.type='button'; b.dataset.rmrOpenClientWorkspace='1'; b.className='rmr-open-client-workspace'; b.textContent='Open Client Workspace'; b.addEventListener('click',openWorkspace);
    const container=title.parentElement || title; container.appendChild(b);
  }
  async function boot() {
    ensureStyle(); await loadIdentity(); addLaunchControl(); addClient360Action();
    const observer=new MutationObserver(()=>{ addLaunchControl(); addClient360Action(); });
    observer.observe(document.body,{childList:true,subtree:true});
    window.addEventListener('keydown',e=>{ if(e.altKey&&e.shiftKey&&e.key.toLowerCase()==='w') openWorkspace(); if(e.key==='Escape') closeWorkspace(); });
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot,{once:true}); else boot();
})();
