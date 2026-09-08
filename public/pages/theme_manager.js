import {api} from '../api.js';
import {state} from '../state.js';
import {$, esc, modal, toast} from '../ui.js';

const STYLE_ORDER = ['classic-blue','metallic-silver','metallic-gold','champagne-gold'];
const fontStack = value => ({
  system: "system-ui,-apple-system,'Segoe UI',sans-serif",
  arial: 'Arial,Helvetica,sans-serif',
  trebuchet: "'Trebuchet MS',Arial,sans-serif",
  georgia: "Georgia,'Times New Roman',serif",
  verdana: 'Verdana,Geneva,sans-serif'
})[value] || "system-ui,-apple-system,'Segoe UI',sans-serif";

const normalizeHex = (value, fallback='#315EFB') => /^#[0-9a-f]{6}$/i.test(String(value||'')) ? String(value).toUpperCase() : fallback;
const rgb = hex => [1,3,5].map(i=>parseInt(normalizeHex(hex).slice(i,i+2),16));
const luminance = hex => rgb(hex).map(x=>{const v=x/255;return v<=.04045?v/12.92:Math.pow((v+.055)/1.055,2.4)}).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
const contrast = (a,b) => {const [hi,lo]=[luminance(a),luminance(b)].sort((x,y)=>y-x);return (hi+.05)/(lo+.05)};
const onColor = hex => contrast(hex,'#FFFFFF')>=contrast(hex,'#111827')?'#FFFFFF':'#111827';
const textOnWhite = hex => {
  hex=normalizeHex(hex);if(contrast(hex,'#FFFFFF')>=4.5)return hex;
  const start=rgb(hex),target=[17,24,39];
  for(let step=1;step<=20;step++){const f=step/20;const candidate='#'+start.map((v,i)=>Math.round(v+(target[i]-v)*f).toString(16).padStart(2,'0')).join('').toUpperCase();if(contrast(candidate,'#FFFFFF')>=4.5)return candidate}
  return '#111827';
};
const styleByKey = (data,key) => (data.workspace_styles||[]).find(item=>item.value===key) || (data.workspace_styles||[])[0] || {value:'classic-blue',label:'RMR Classic Blue',short_label:'Classic Blue',description:'Original soft-blue workspace.',preview_url:'/static/assets/workspace-themes/classic-blue.jpg',defaults:{},tokens:{}};
const currentStyle = (data,theme=data.theme||{}) => styleByKey(data,theme.workspace_style||'classic-blue');
const previewStyle = (data,theme) => {
  const style=currentStyle(data,theme), tokens=style.tokens||{};
  const vars={
    '--preview-primary':normalizeHex(theme.primary_color),
    '--preview-secondary':normalizeHex(theme.secondary_color,'#F4F7FB'),
    '--preview-accent':normalizeHex(theme.accent_color,'#7C5CFC'),
    '--preview-on-primary':theme.on_primary||onColor(theme.primary_color),
    '--preview-on-secondary':theme.on_secondary||onColor(theme.secondary_color),
    '--preview-on-accent':theme.on_accent||onColor(theme.accent_color),
    '--preview-primary-text':theme.primary_text||textOnWhite(theme.primary_color),
    '--preview-accent-text':theme.accent_text||textOnWhite(theme.accent_color),
    '--preview-font':fontStack(theme.font_family),
    '--preview-nav':tokens.nav_background||'#07192F',
    '--preview-nav-end':tokens.nav_background_end||'#0B2C52',
    '--preview-nav-text':tokens.nav_text||'#E8F0FA',
    '--preview-nav-muted':tokens.nav_muted||'#9DB0C7',
    '--preview-nav-active':tokens.nav_active||'#315EFB',
    '--preview-nav-active-text':tokens.nav_active_text||'#FFFFFF',
    '--preview-canvas':tokens.canvas||'#F3F7FB',
    '--preview-surface':tokens.surface||'#FFFFFF',
    '--preview-surface-alt':tokens.surface_alt||'#EAF1F8',
    '--preview-line':tokens.line||'#D7E2EE',
    '--preview-topbar':tokens.topbar||'#FFFFFF',
    '--preview-hero-start':tokens.hero_start||'#FDFEFF',
    '--preview-hero-end':tokens.hero_end||'#E4EFFA',
    '--preview-hero-text':tokens.hero_text||'#142A43',
    '--preview-action':tokens.action||'#315EFB',
    '--preview-action-text':tokens.action_text||'#FFFFFF',
    '--preview-display-accent':tokens.display_accent||'#315EFB',
    '--preview-shadow':tokens.shadow||'rgba(22,62,102,.12)',
    '--preview-pattern-a':tokens.pattern_a||'rgba(49,94,251,.08)',
    '--preview-pattern-b':tokens.pattern_b||'rgba(255,255,255,.88)'
  };
  return Object.entries(vars).map(([k,v])=>`${k}:${esc(v)}`).join(';');
};

export function themeSummaryCard(result, {buttonId='manage-tenant-theme', compact=false}={}) {
  const theme=result?.theme || {};
  const active=Boolean(theme.enabled);
  const brand=theme.brand_name || result?.tenant_name || 'Client';
  const style=currentStyle(result,theme);
  return `<section class="theme-summary-card ${compact?'compact':''}">
    <div class="theme-summary-preview" style="${previewStyle(result,theme)}">
      <div class="theme-summary-logo">${theme.has_logo?`<img src="${esc(theme.logo_url)}" alt="${esc(brand)} logo">`:esc(brand.slice(0,1).toUpperCase())}</div>
      <div><strong>${esc(brand)}</strong><small>${active?`${esc(style.label)} workspace active`:'RMR Global default theme'}</small></div>
    </div>
    <div class="theme-swatches" aria-label="Theme colors"><span style="background:${esc(theme.primary_color||'#315EFB')}"></span><span style="background:${esc(theme.secondary_color||'#F4F7FB')}"></span><span style="background:${esc(theme.accent_color||'#7C5CFC')}"></span></div>
    ${result?.can_manage?`<button class="button secondary small" id="${esc(buttonId)}">Manage Branding</button>`:''}
  </section>`;
}

function workspaceStyleCards(data) {
  const selected=data.theme.workspace_style||'classic-blue';
  const rows=STYLE_ORDER.map(key=>styleByKey(data,key));
  return `<fieldset class="workspace-style-fieldset"><legend>Choose Workspace Style</legend><p class="workspace-style-help">Select one RMR-controlled visual preset. Screens, workflows, permissions, CRM, and data remain unchanged.</p><div class="workspace-style-grid">${rows.map(style=>`
    <label class="workspace-style-card ${style.value===selected?'selected':''}" data-workspace-style="${esc(style.value)}">
      <input type="radio" name="workspace_style" value="${esc(style.value)}" ${style.value===selected?'checked':''}>
      <span class="workspace-style-image"><img src="${esc(style.preview_url)}" alt="${esc(style.label)} workspace preview"></span>
      <span class="workspace-style-copy"><strong>${esc(style.label)}</strong><small>${esc(style.description)}</small></span>
      <span class="workspace-style-check" aria-hidden="true">✓</span>
    </label>`).join('')}</div></fieldset>`;
}

function previewMarkup(data) {
  const theme=data.theme,brand=theme.brand_name||data.tenant_name,style=currentStyle(data,theme);
  return `<div class="theme-live-preview workspace-preview-${esc(style.value)}" id="theme-live-preview" style="${previewStyle(data,theme)}">
    <aside><div class="theme-preview-logo" id="theme-preview-logo">${theme.has_logo?`<img src="${esc(theme.logo_url)}" alt="${esc(brand)} logo">`:esc(brand.slice(0,1).toUpperCase())}</div><strong id="theme-preview-name">${esc(brand)}</strong><small id="theme-preview-style-name">${esc(style.label)} · Powered by RMR Global</small><span class="theme-preview-nav active">Dashboard</span><span class="theme-preview-nav">CRM</span><span class="theme-preview-nav">Reporting</span></aside>
    <main><div class="theme-preview-top" id="theme-preview-top">${esc(brand)} Workspace</div><section><small>CLIENT OPERATIONS</small><h3>One branded workspace for growth.</h3><p>The selected preset changes only the authenticated workspace presentation.</p><button type="button">Primary action</button><button class="secondary" type="button">Secondary action</button></section></main>
  </div>`;
}

function formMarkup(data) {
  const t=data.theme;
  const fonts=(data.allowed_fonts||[]).map(x=>`<option value="${esc(x.value)}" ${x.value===t.font_family?'selected':''}>${esc(x.label)}</option>`).join('');
  return `<div class="theme-boundary-note"><strong>Authenticated application theme only</strong><span>This does not redesign the client's public website or any externally hosted website.</span></div>
  ${workspaceStyleCards(data)}
  ${previewMarkup(data)}
  <form id="tenant-theme-form" class="theme-form">
    <input type="hidden" name="workspace_style" value="${esc(t.workspace_style||'classic-blue')}">
    <label class="theme-toggle"><input type="checkbox" name="enabled" ${t.enabled?'checked':''}><span>Use selected workspace style and tenant branding</span></label>
    <div class="form-grid">
      <div class="field"><label>Tenant brand name</label><input name="brand_name" maxlength="160" value="${esc(t.brand_name||data.tenant_name)}"></div>
      <div class="field"><label>Approved typography</label><select name="font_family">${fonts}</select></div>
      <div class="field theme-color-field"><label>Primary brand color</label><div><input type="color" name="primary_color_picker" value="${esc(t.primary_color)}"><input name="primary_color" value="${esc(t.primary_color)}" pattern="#[0-9A-Fa-f]{6}"></div></div>
      <div class="field theme-color-field"><label>Soft secondary color</label><div><input type="color" name="secondary_color_picker" value="${esc(t.secondary_color)}"><input name="secondary_color" value="${esc(t.secondary_color)}" pattern="#[0-9A-Fa-f]{6}"></div></div>
      <div class="field theme-color-field"><label>Accent color</label><div><input type="color" name="accent_color_picker" value="${esc(t.accent_color)}"><input name="accent_color" value="${esc(t.accent_color)}" pattern="#[0-9A-Fa-f]{6}"></div></div>
      <div class="field"><label>Tenant logo (PNG, JPEG, or WebP; max 2 MB)</label><input type="file" name="logo" accept="image/png,image/jpeg,image/webp"><small>${t.has_logo?'A saved logo is active. Choose a file to replace it.':'No tenant logo is saved; the brand initial is used.'}</small></div>
    </div>
  </form>`;
}

function wirePreview(root,data) {
  const form=$('#tenant-theme-form',root),preview=$('#theme-live-preview',root),name=$('#theme-preview-name',root),styleName=$('#theme-preview-style-name',root),top=$('#theme-preview-top',root),logo=$('#theme-preview-logo',root);
  const sync=()=>{
    const brand=form.brand_name.value.trim()||data.tenant_name;
    const primary=normalizeHex(form.primary_color.value),secondary=normalizeHex(form.secondary_color.value,'#F4F7FB'),accent=normalizeHex(form.accent_color.value,'#7C5CFC');
    const style=styleByKey(data,form.workspace_style.value), tokens=style.tokens||{};
    const values={
      '--preview-primary':primary,'--preview-secondary':secondary,'--preview-accent':accent,
      '--preview-on-primary':onColor(primary),'--preview-on-secondary':onColor(secondary),'--preview-on-accent':onColor(accent),
      '--preview-primary-text':textOnWhite(primary),'--preview-accent-text':textOnWhite(accent),'--preview-font':fontStack(form.font_family.value),
      '--preview-nav':tokens.nav_background,'--preview-nav-end':tokens.nav_background_end,'--preview-nav-text':tokens.nav_text,'--preview-nav-muted':tokens.nav_muted,
      '--preview-nav-active':tokens.nav_active,'--preview-nav-active-text':tokens.nav_active_text,'--preview-canvas':tokens.canvas,'--preview-surface':tokens.surface,
      '--preview-surface-alt':tokens.surface_alt,'--preview-line':tokens.line,'--preview-topbar':tokens.topbar,'--preview-hero-start':tokens.hero_start,
      '--preview-hero-end':tokens.hero_end,'--preview-hero-text':tokens.hero_text,'--preview-action':tokens.action,'--preview-action-text':tokens.action_text,
      '--preview-display-accent':tokens.display_accent,'--preview-shadow':tokens.shadow,'--preview-pattern-a':tokens.pattern_a,'--preview-pattern-b':tokens.pattern_b
    };
    Object.entries(values).forEach(([k,v])=>{if(v)preview.style.setProperty(k,v)});
    preview.className=`theme-live-preview workspace-preview-${style.value}${form.enabled.checked?'':' disabled'}`;
    name.textContent=brand; top.textContent=`${brand} Workspace`; styleName.textContent=`${style.label} · Powered by RMR Global`;
    if(!logo.querySelector('img'))logo.textContent=brand.slice(0,1).toUpperCase();
    root.querySelectorAll('.workspace-style-card').forEach(card=>card.classList.toggle('selected',card.dataset.workspaceStyle===style.value));
  };
  root.querySelectorAll('.workspace-style-card').forEach(card=>card.addEventListener('click',()=>{
    const style=styleByKey(data,card.dataset.workspaceStyle);
    form.workspace_style.value=style.value;
    const radio=card.querySelector('input[type=radio]');if(radio)radio.checked=true;
    const defaults=style.defaults||{};
    [['primary_color','primary_color_picker'],['secondary_color','secondary_color_picker'],['accent_color','accent_color_picker']].forEach(([text,picker])=>{
      const value=defaults[text];if(value){form[text].value=value;form[picker].value=value}
    });
    if(defaults.font_family)form.font_family.value=defaults.font_family;
    form.enabled.checked=true;sync();
  }));
  [['primary_color','primary_color_picker'],['secondary_color','secondary_color_picker'],['accent_color','accent_color_picker']].forEach(([text,picker])=>{
    form[picker].addEventListener('input',()=>{form[text].value=form[picker].value.toUpperCase();sync()});
    form[text].addEventListener('input',()=>{if(/^#[0-9a-f]{6}$/i.test(form[text].value)){form[picker].value=form[text].value;sync()}});
  });
  ['brand_name','font_family','enabled'].forEach(field=>form[field].addEventListener('input',sync));
  form.logo.addEventListener('change',()=>{const file=form.logo.files[0];if(!file)return;const url=URL.createObjectURL(file);logo.innerHTML=`<img src="${url}" alt="Logo preview">`;sync()});
  sync();
}

export async function openThemeManager(tenantId, ctx, {title='Workspace Style & Branding'}={}) {
  let data;
  try{data=await api(`/api/tenants/${tenantId}/theme`)}catch(error){toast(error.message,'error');return}
  if(!data.can_manage){toast('You can view this theme but do not have permission to change it.','error');return}
  modal({title:`${title} — ${esc(data.tenant_name)}`,wide:true,body:formMarkup(data),footer:`<button class="button secondary" data-close-modal>Cancel</button>${data.theme.has_logo?'<button class="button secondary" id="remove-theme-logo">Remove Logo</button>':''}<button class="button secondary" id="reset-tenant-theme">Reset to RMR Default</button><button class="button" id="save-tenant-theme">Save & Apply</button>`,onOpen:(root,close)=>{
    wirePreview(root,data);
    $('#save-tenant-theme',root).addEventListener('click',async()=>{
      const form=$('#tenant-theme-form',root);if(!form.reportValidity())return;
      try{
        let result=await api(`/api/tenants/${tenantId}/theme`,{method:'PATCH',body:{enabled:form.enabled.checked,workspace_style:form.workspace_style.value,brand_name:form.brand_name.value,primary_color:form.primary_color.value,secondary_color:form.secondary_color.value,accent_color:form.accent_color.value,font_family:form.font_family.value}});
        const logo=form.logo.files[0];
        if(logo){const fd=new FormData();fd.append('file',logo);result=await api(`/api/tenants/${tenantId}/theme/logo`,{method:'POST',body:fd})}
        toast('Workspace style and tenant branding saved');close();await ctx.refreshTenantTheme({rerender:true,tenantId,result});
      }catch(error){toast(error.message,'error')}
    });
    $('#remove-theme-logo',root)?.addEventListener('click',async()=>{if(!confirm('Remove the saved tenant logo?'))return;try{await api(`/api/tenants/${tenantId}/theme/logo`,{method:'DELETE',body:{}});toast('Tenant logo removed');close();await ctx.refreshTenantTheme({rerender:true,tenantId})}catch(error){toast(error.message,'error')}});
    $('#reset-tenant-theme',root).addEventListener('click',async()=>{if(!confirm(`Reset ${data.tenant_name} to the standard RMR Global theme? Other tenants will not be affected.`))return;try{await api(`/api/tenants/${tenantId}/theme/reset`,{method:'POST',body:{}});toast('Tenant theme reset to RMR Global default');close();await ctx.refreshTenantTheme({rerender:true,tenantId})}catch(error){toast(error.message,'error')}});
  }});
}

export async function enhanceThemeForClientAdmin(page,ctx) {
  try{
    const data=await api(`/api/tenants/${state.selectedTenantId}/theme`);
    const panel=document.createElement('section');
    panel.className='ca-section tenant-theme-settings';
    panel.innerHTML=`<div class="ca-section-head"><div><h2>Workspace Style & Branding</h2><p>Choose one of four RMR-controlled workspace designs and apply your own approved tenant branding.</p></div></div>${themeSummaryCard(data,{buttonId:'client-manage-theme',compact:true})}`;
    page.querySelector('.page-head')?.insertAdjacentElement('afterend',panel);
    $('#client-manage-theme',panel)?.addEventListener('click',()=>openThemeManager(state.selectedTenantId,ctx,{title:'Workspace Style & Branding'}));
  }catch(error){console.warn('Tenant branding panel unavailable',error)}
}
