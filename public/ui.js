import {state, isGlobalAdmin, selectedTenant} from './state.js';
import {applyTenantTheme, tenantBrandMarkup} from './tenant-theme.js';

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

export function bindRouteDelegation(navigate) {
  const appRoot = $('#app');
  if (!appRoot || typeof navigate !== 'function') return;
  if (appRoot._rmrRouteDelegate) {
    appRoot.removeEventListener('click', appRoot._rmrRouteDelegate, true);
  }
  const routeDelegate = event => {
    const origin = event.target?.closest ? event.target : event.target?.parentElement;
    const control = origin?.closest?.('[data-route],[data-v53-route]');
    if (!control || !appRoot.contains(control) || control.disabled || control.getAttribute('aria-disabled') === 'true') return;
    const route = control.dataset.route || control.dataset.v53Route;
    if (!route) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    navigate(route);
  };
  appRoot._rmrRouteDelegate = routeDelegate;
  appRoot.addEventListener('click', routeDelegate, true);
}
export const esc = (value = '') => String(value).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
export const money = cents => new Intl.NumberFormat('en-US', {style:'currency', currency:'USD', maximumFractionDigits: Number(cents) % 100 ? 2 : 0}).format((Number(cents) || 0) / 100);
export const number = value => new Intl.NumberFormat('en-US').format(Number(value) || 0);
export const pct = value => `${Number(value || 0).toFixed(Number(value || 0) % 1 ? 1 : 0)}%`;
export const dateFmt = value => value ? new Intl.DateTimeFormat('en-US', {month:'short', day:'numeric', year:'numeric'}).format(new Date(value)) : '—';
export const acronym = term => `<abbr class="acronym" data-term="${esc(term)}">${esc(term)}</abbr>`;
export const badge = (text, tone='gray') => `<span class="badge ${tone}"><span class="status-dot"></span>${esc(text)}</span>`;
export const statusTone = status => {
  const s = String(status || '').toLowerCase();
  if (['active','live','strong','healthy','complete','closed won','approved','published','accepted'].some(x => s.includes(x))) return 'green';
  if (['attention','moderate','pending','requested','in progress','scheduled','draft','onboarding','awaiting'].some(x => s.includes(x))) return 'amber';
  if (['risk','declined','closed lost','suspended','failed','blocked','expired','revoked'].some(x => s.includes(x))) return 'red';
  if (['private','priority'].some(x => s.includes(x))) return 'purple';
  return 'gray';
};

export function toast(message, type='success') {
  const region = $('#toast-region');
  if (!region) return;
  const el = document.createElement('div');
  el.className = `toast ${type === 'error' ? 'error' : ''}`;
  el.textContent = message;
  region.appendChild(el);
  setTimeout(() => el.remove(), 5200);
}

export function clearFieldErrors(root) {
  $$('[data-field-error]', root).forEach(el => el.remove());
  $$('.field-error-input', root).forEach(el => el.classList.remove('field-error-input'));
}

export function applyFieldErrors(root, errors={}) {
  clearFieldErrors(root);
  Object.entries(errors || {}).forEach(([name, message]) => {
    const input = root.querySelector(`[name="${CSS.escape(name)}"]`);
    if (!input) return;
    input.classList.add('field-error-input');
    const note = document.createElement('small');
    note.className = 'field-error';
    note.dataset.fieldError = name;
    note.textContent = message;
    input.closest('.field')?.appendChild(note);
  });
  const first = root.querySelector('.field-error-input');
  first?.focus();
}

export function modal({title, body, footer='', wide=false, onOpen, closeOnBackdrop=false}) {
  const root = $('#modal-root');
  root.innerHTML = `<div class="modal-backdrop"><section class="modal ${wide ? 'wide':''}" role="dialog" aria-modal="true"><header class="modal-head"><div><h2>${title}</h2></div><button class="icon-button" data-close-modal aria-label="Close">×</button></header><div class="modal-body">${body}</div><footer class="modal-foot">${footer}</footer></section></div>`;
  const close = () => { root.innerHTML = ''; };
  $$('[data-close-modal]', root).forEach(button => button.addEventListener('click', close));
  if (closeOnBackdrop) $('.modal-backdrop', root)?.addEventListener('click', e => { if (e.target.classList.contains('modal-backdrop')) close(); });
  onOpen?.(root, close);
  return close;
}

export function pageHead(title, subtitle='', actions='', breadcrumbs='') {
  return `${breadcrumbs ? `<nav class="breadcrumbs" aria-label="Breadcrumb">${breadcrumbs}</nav>` : ''}<div class="page-head"><div><h1>${title}</h1>${subtitle ? `<p>${subtitle}</p>`:''}</div><div class="page-actions">${actions}</div></div>`;
}

export function breadcrumb(items=[]) {
  return items.map((item,index)=>item.route ? `<button class="breadcrumb-link" data-breadcrumb-route="${esc(item.route)}">${esc(item.label)}</button>${index < items.length-1 ? '<span>›</span>' : ''}` : `<strong>${esc(item.label)}</strong>${index < items.length-1 ? '<span>›</span>' : ''}`).join('');
}

export function readonlyBanner() {
  return `<div class="readonly-banner">Client operations are view-only for RMR and Step2. Authorized client users manage their own business records.</div>`;
}

export function loading() { return `<div class="loading">Loading…</div>`; }
export function empty(title, text, action='') { return `<div class="empty-state"><strong>${esc(title)}</strong><span>${esc(text)}</span>${action}</div>`; }

export function navItems() {
  const clientItems = state.modules.length
    ? state.modules.filter(item => item.enabled).map(item => [item.key, item.label, item.icon])
    : [
        ['home','Dashboard','⌂'],
        ['website','Website','◫'],
        ['crm','CRM','▤'],
        ['piq','ProspectIQ','◇'],
        ['campaigns','Campaigns & Social','◐'],
        ['email','Email & Activities','✉'],
        ['forecast','Forecasting','↗'],
        ['reports','Reporting','▥'],
        ['training','Training','▶'],
        ['organization','Team & Settings','♙'],
        ['solutions','Solutions','✦']
      ];
  if (isGlobalAdmin() && !state.adminClientWorkspace) {
    return [
      ['portfolio','Portfolio Command Center','▦'],
      ['client-success','Client Success Intelligence','◎'],
      ['pricing','Client Pricing','$'],
      ['partner-economics','Partner Economics','◈'],
      ['onboarding','Client Onboarding','✓'],
      ['service-requests','Service Requests','↗'],
      ['training','Training Administration','▶'],
      ['support-access','Support Access Audit','◉'],
      ['system','System Health','●']
    ];
  }
  return clientItems;
}

export function renderShell() {
  applyTenantTheme();
  const user = state.user;
  const tenant = selectedTenant();
  const clientWorkspace = !isGlobalAdmin() || state.adminClientWorkspace;
  const initials = user.full_name.split(/\s+/).map(x => x[0]).join('').slice(0,2).toUpperCase();
  const nav = navItems().map(([route,label,icon]) => `<button class="nav-link" data-nav="${route}"><span class="nav-icon">${icon}</span><span>${esc(label)}</span></button>`).join('');
  const tenantOptions = state.tenants.map(t => `<option value="${t.id}" ${t.id === state.selectedTenantId ? 'selected':''}>${esc(t.name)}</option>`).join('');
  const workspaceBanner = isGlobalAdmin() && state.adminClientWorkspace ? `<div class="managed-session-banner ${state.managedSession ? 'active' : 'readonly'}"><div><strong>${state.managedSession ? 'Authorized & Audited Client Workspace' : 'Client Workspace Preview'}</strong><span>${state.managedSession ? `Acting as ${esc(user.full_name)} inside ${esc(tenant?.name||'client')}. Every action is attributed and audited.` : `Viewing ${esc(tenant?.name||'client')} as ${esc(user.full_name)}. Start an authorized session to perform managed services.`}</span></div><div class="managed-actions">${state.managedSession ? '<button class="button small" id="end-managed-session">End managed session</button>' : '<button class="button small" id="start-managed-session">Start authorized session</button>'}<button class="button secondary small" id="exit-client-workspace">Return to Portfolio</button></div></div>` : '';
  document.querySelector('#app').innerHTML = `<div class="app-shell"><aside class="sidebar" id="sidebar"><div class="sidebar-brand">${tenantBrandMarkup(clientWorkspace)}</div><div class="nav-label">${clientWorkspace ? esc(tenant?.name || 'CLIENT') : 'RMR / STEP2'}</div>${nav}<div class="sidebar-footer">v5.4.1.2<br>Interaction Regression Correction</div></aside><main class="main-area"><header class="topbar"><button class="icon-button mobile-nav-toggle" id="mobile-nav">☰</button><button class="icon-button" id="app-back" title="Back" disabled>←</button><div class="topbar-location grow" id="topbar-location">${isGlobalAdmin() ? `<select class="input tenant-select" id="tenant-selector"><option value="">Select client…</option>${tenantOptions}</select>` : `<strong>${esc(tenant?.name || '')}</strong>`}</div><button class="button secondary small" id="notifications-button">Notifications</button><div class="identity"><div class="avatar">${initials}</div><div class="identity-copy"><strong>${esc(user.full_name)}</strong><small>${esc(user.global_role || user.tenant_role || '')}</small></div></div><button class="icon-button" id="logout-button" title="Sign out">↪</button></header>${workspaceBanner}<div class="main-content" id="page">${loading()}</div></main></div>`;
}

export function bindGlobalUI({navigate, goBack, logout, onTenantChange, showNotifications}) {
  bindRouteDelegation(navigate);
  $$('.nav-link').forEach(btn => btn.addEventListener('click', () => navigate(btn.dataset.nav)));

  $('#logout-button')?.addEventListener('click', logout);
  $('#app-back')?.addEventListener('click', goBack);
  $('#tenant-selector')?.addEventListener('change', e => onTenantChange(e.target.value));
  $('#notifications-button')?.addEventListener('click', showNotifications);
  $('#mobile-nav')?.addEventListener('click', () => $('#sidebar')?.classList.toggle('open'));
  installTooltips();
}

export function updateBackButton(enabled) {
  const button = $('#app-back');
  if (button) button.disabled = !enabled;
}

export function bindBreadcrumbs(navigate) {
  $$('[data-breadcrumb-route]').forEach(btn => btn.addEventListener('click', () => navigate(btn.dataset.breadcrumbRoute)));
}

export function setActiveNav(route) {
  $$('.nav-link').forEach(btn => btn.classList.toggle('active', btn.dataset.nav === route));
}

export function installTooltips() {
  let tooltip;
  const show = target => {
    const term = target.dataset.term;
    const text = state.glossary[term];
    if (!text) return;
    tooltip?.remove();
    tooltip = document.createElement('div');
    tooltip.className = 'tooltip';
    tooltip.textContent = text;
    document.body.appendChild(tooltip);
    const rect = target.getBoundingClientRect();
    const pad = 10;
    let left = rect.left + rect.width / 2 - tooltip.offsetWidth / 2;
    left = Math.max(pad, Math.min(left, window.innerWidth - tooltip.offsetWidth - pad));
    let top = rect.top - tooltip.offsetHeight - 8;
    if (top < pad) top = rect.bottom + 8;
    if (top + tooltip.offsetHeight > window.innerHeight - pad) top = Math.max(pad, window.innerHeight - tooltip.offsetHeight - pad);
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  };
  const hide = () => { tooltip?.remove(); tooltip = null; };
  $$('.acronym').forEach(el => {
    el.addEventListener('mouseenter', () => show(el));
    el.addEventListener('mouseleave', hide);
    el.addEventListener('focus', () => show(el));
    el.addEventListener('blur', hide);
    el.addEventListener('click', () => tooltip ? hide() : show(el));
    el.tabIndex = 0;
  });
}
