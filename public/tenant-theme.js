import {api} from './api.js';
import {state, isGlobalAdmin, selectedTenant} from './state.js';

const STYLE_CLASSES = [
  'workspace-style-classic-blue',
  'workspace-style-metallic-silver',
  'workspace-style-metallic-gold',
  'workspace-style-champagne-gold'
];

const DEFAULT_TOKENS = {
  nav_background: '#07192F', nav_background_end: '#0B2C52', nav_text: '#E8F0FA', nav_muted: '#9DB0C7',
  nav_active: '#315EFB', nav_active_text: '#FFFFFF', canvas: '#F3F7FB', surface: '#FFFFFF',
  surface_alt: '#EAF1F8', line: '#D7E2EE', topbar: '#FFFFFF', hero_start: '#FDFEFF', hero_end: '#E4EFFA',
  hero_text: '#142A43', metallic: '#8DB6DC', action: '#315EFB', action_text: '#FFFFFF',
  display_accent: '#315EFB', chart: '#315EFB', shadow: 'rgba(22,62,102,.12)',
  pattern_a: 'rgba(49,94,251,.08)', pattern_b: 'rgba(255,255,255,.88)'
};

const DEFAULTS = {
  enabled: false,
  workspace_style: 'classic-blue',
  workspace_style_label: 'RMR Classic Blue',
  workspace_tokens: DEFAULT_TOKENS,
  brand_name: '',
  primary_color: '#315EFB',
  secondary_color: '#F4F7FB',
  accent_color: '#7C5CFC',
  font_family: 'system',
  on_primary: '#FFFFFF',
  on_secondary: '#111827',
  on_accent: '#FFFFFF',
  primary_text: '#315EFB',
  accent_text: '#5C3FD1',
  has_logo: false,
  logo_url: ''
};

const FONT_STACKS = {
  system: "system-ui,-apple-system,'Segoe UI',sans-serif",
  arial: 'Arial,Helvetica,sans-serif',
  trebuchet: "'Trebuchet MS',Arial,sans-serif",
  georgia: "Georgia,'Times New Roman',serif",
  verdana: 'Verdana,Geneva,sans-serif'
};

const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

export async function refreshTenantTheme() {
  if (!state.selectedTenantId) {
    state.tenantTheme = null;
    applyTenantTheme();
    return null;
  }
  try {
    state.tenantTheme = await api(`/api/tenants/${state.selectedTenantId}/theme`);
  } catch (error) {
    console.warn('Tenant theme unavailable', error);
    state.tenantTheme = null;
  }
  applyTenantTheme();
  return state.tenantTheme;
}

export function clearTenantTheme() {
  state.tenantTheme = null;
  applyTenantTheme();
}

const ADMIN_TENANT_THEME_ROUTES = new Set(['client-360']);

export function tenantThemeIsActive() {
  const theme = state.tenantTheme?.theme;
  const inClientWorkspace = !isGlobalAdmin() || state.adminClientWorkspace;
  const inTenantScopedAdminView = isGlobalAdmin() && ADMIN_TENANT_THEME_ROUTES.has(state.route);
  return Boolean((inClientWorkspace || inTenantScopedAdminView) && state.selectedTenantId && theme?.enabled);
}

export function applyTenantTheme() {
  const root = document.documentElement;
  const body = document.body;
  const active = tenantThemeIsActive();
  const theme = active ? {...DEFAULTS, ...state.tenantTheme.theme} : DEFAULTS;
  const tokens = {...DEFAULT_TOKENS, ...(theme.workspace_tokens || {})};
  const variables = {
    '--tenant-primary': theme.primary_color,
    '--tenant-secondary': theme.secondary_color,
    '--tenant-accent': theme.accent_color,
    '--tenant-on-primary': theme.on_primary,
    '--tenant-on-secondary': theme.on_secondary,
    '--tenant-on-accent': theme.on_accent,
    '--tenant-primary-text': theme.primary_text,
    '--tenant-accent-text': theme.accent_text,
    '--tenant-font-family': FONT_STACKS[theme.font_family] || FONT_STACKS.system,
    '--workspace-nav': tokens.nav_background,
    '--workspace-nav-end': tokens.nav_background_end,
    '--workspace-nav-text': tokens.nav_text,
    '--workspace-nav-muted': tokens.nav_muted,
    '--workspace-nav-active': tokens.nav_active,
    '--workspace-nav-active-text': tokens.nav_active_text,
    '--workspace-canvas': tokens.canvas,
    '--workspace-surface': tokens.surface,
    '--workspace-surface-alt': tokens.surface_alt,
    '--workspace-line': tokens.line,
    '--workspace-topbar': tokens.topbar,
    '--workspace-hero-start': tokens.hero_start,
    '--workspace-hero-end': tokens.hero_end,
    '--workspace-hero-text': tokens.hero_text,
    '--workspace-metallic': tokens.metallic,
    '--workspace-action': tokens.action,
    '--workspace-action-text': tokens.action_text,
    '--workspace-display-accent': tokens.display_accent,
    '--workspace-chart': tokens.chart,
    '--workspace-shadow': tokens.shadow,
    '--workspace-pattern-a': tokens.pattern_a,
    '--workspace-pattern-b': tokens.pattern_b
  };
  Object.entries(variables).forEach(([key,value]) => root.style.setProperty(key, value));
  body.classList.toggle('tenant-theme-active', active);
  STYLE_CLASSES.forEach(name => body.classList.remove(name));
  if (active) body.classList.add(`workspace-style-${theme.workspace_style || 'classic-blue'}`);
  body.dataset.tenantTheme = active ? state.selectedTenantId : '';
  body.dataset.workspaceStyle = active ? (theme.workspace_style || 'classic-blue') : '';
}

export function tenantBrandMarkup(clientWorkspace) {
  const tenant = selectedTenant();
  const active = Boolean(clientWorkspace && tenantThemeIsActive());
  const theme = active ? {...DEFAULTS, ...state.tenantTheme.theme} : DEFAULTS;
  const brandName = active ? (theme.brand_name || tenant?.name || 'Client Workspace') : 'RMR Global';
  const subtitle = active
    ? `${theme.workspace_style_label || 'Workspace Style'} · Powered by RMR Global`
    : (clientWorkspace ? 'Business growth workspace' : 'Portfolio operations');
  const mark = active && theme.has_logo
    ? `<div class="brand-mark tenant-brand-mark"><img src="${esc(theme.logo_url)}" alt="${esc(brandName)} logo"></div>`
    : `<div class="brand-mark tenant-brand-mark">${esc(active ? brandName.slice(0,1).toUpperCase() : 'R')}</div>`;
  return `${mark}<div><strong>${esc(brandName)}</strong><span>${esc(subtitle)}</span></div>`;
}

export function currentTheme() {
  return state.tenantTheme?.theme || {...DEFAULTS, brand_name: selectedTenant()?.name || ''};
}
