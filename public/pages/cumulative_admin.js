import {api} from '../api.js';
import {state} from '../state.js';
import {$, $$, badge, dateFmt, esc, modal, money, number, pageHead, statusTone, toast} from '../ui.js';

const supported = new Set(['pricing','partner-economics']);
const cents = value => Math.round((Number(value)||0)*100);
const dollars = value => (Number(value||0)/100).toFixed(2);
const f = (label,name,type='text',value='',extra='') => `<div class="field"><label>${esc(label)}</label><input name="${esc(name)}" type="${type}" value="${esc(value??'')}" ${extra}></div>`;
const sel = (label,name,options,value='') => `<div class="field"><label>${esc(label)}</label><select name="${esc(name)}">${options.map(([v,l])=>`<option value="${esc(v)}" ${String(v)===String(value)?'selected':''}>${esc(l)}</option>`).join('')}</select></div>`;
const textarea = (label,name,value='') => `<div class="field full"><label>${esc(label)}</label><textarea name="${esc(name)}">${esc(value||'')}</textarea></div>`;
const pct = value => `${Number(value||0).toFixed(1).replace('.0','')}%`;

export function cumulativeAdminApplies(route){return supported.has(route);}

export async function renderCumulativeAdmin(route,page,ctx){
  if(route==='pricing') await pricing(page,ctx);
  else if(route==='partner-economics') await economics(page,ctx);
  return true;
}

async function pricing(page,ctx){
  const portfolio=await api('/api/portfolio/summary');
  const selected=state.selectedTenantId||portfolio.tenants[0]?.id;
  if(!selected){page.innerHTML=pageHead('Client Pricing','Configure client-specific service pricing and revenue share.');return;}
  if(!state.selectedTenantId) state.selectedTenantId=selected;
  const data=await api(`/api/v522/admin/tenants/${selected}/commercial-terms`);
  const options=portfolio.tenants.map(t=>`<option value="${t.id}" ${t.id===selected?'selected':''}>${esc(t.name)}</option>`).join('');
  page.innerHTML=`${pageHead('Client Pricing & Revenue Share','Set negotiated pricing and RMR/Step2 economics independently for every client service.',`<button class="button" id="v522-add-service">+ Add Client Service</button>`)}
  <section class="premium-toolbar"><div><span class="eyebrow">CLIENT COMMERCIAL AGREEMENT</span><h2>${esc(data.tenant.name)}</h2><p>Standard pricing remains in the service catalog. The client schedule below controls this client’s actual price, cadence, seller and service-level revenue split.</p></div><label class="premium-selector">Select client<select id="v522-pricing-client">${options}</select></label></section>
  ${data.unreviewed_defaults?`<div class="premium-alert warn"><strong>${data.unreviewed_defaults} service${data.unreviewed_defaults===1?'':'s'} still use catalog-default economics.</strong><span>Open each service and save the client-specific terms before relying on Partner Economics.</span></div>`:''}
  <div class="premium-kpis">
    ${kpi('Client MRR',money(data.totals.mrr_cents),'Active recurring client prices')}
    ${kpi('RMR Monthly Share',money(data.totals.rmr_share_cents),'From service-level terms')}
    ${kpi('Step2 Monthly Share',money(data.totals.step2_share_cents),'From service-level terms')}
    ${kpi('Services',number(data.items.length),'Independent commercial terms')}
  </div>
  <section class="premium-panel"><header><div><h2>Service Schedule</h2><p>Edit any row. One service change does not alter another service or another client.</p></div></header>
  <div class="premium-table-wrap"><table class="premium-table"><thead><tr><th>Service</th><th>Standard</th><th>Client Price</th><th>Cadence</th><th>RMR</th><th>Step2</th><th>Direct Cost</th><th>Seller</th><th>Effective</th><th>Status</th><th></th></tr></thead><tbody>
  ${data.items.map(item=>serviceRow(item)).join('')||'<tr><td colspan="11">No services are on this client schedule.</td></tr>'}
  </tbody></table></div></section>`;
  $('#v522-pricing-client').addEventListener('change',e=>{state.selectedTenantId=e.target.value;localStorage.setItem('rmr_selected_tenant',state.selectedTenantId);pricing(page,ctx)});
  $('#v522-add-service').addEventListener('click',()=>addService(data,ctx));
  $$('[data-v522-edit-term]').forEach(btn=>btn.addEventListener('click',()=>editTerm(data.items.find(x=>x.tenant_service.id===btn.dataset.v522EditTerm),ctx)));
}

function kpi(label,value,note){return `<article class="premium-kpi"><span>${label}</span><strong>${value}</strong><small>${note}</small></article>`}
function serviceRow(item){const t=item.tenant_service,c=item.catalog,e=item.commercial_term,calc=item.calculation;return `<tr>
<td><strong>${esc(c.name)}</strong><small>${esc(c.code)} · ${esc(item.terms_source==='explicit_client_terms'?'Client terms saved':'Catalog defaults — review required')}</small></td>
<td>${money(c.standard_price_cents)}</td><td><strong>${money(t.contract_price_cents)}</strong></td><td>${esc(t.cadence)}</td>
<td>${pct(calc.rmr_share_pct)}<small>${money(calc.rmr_share_cents)}/mo</small></td><td>${pct(calc.step2_share_pct)}<small>${money(calc.step2_share_cents)}/mo</small></td>
<td>${money(calc.monthly_direct_cost_cents)}<small>${esc(calc.split_basis)} split basis</small></td>
<td>${esc(e?.seller_name||e?.seller_org||item.tenant.seller_name||item.tenant.seller_org||'—')}</td><td>${dateFmt(t.effective_date)}</td><td>${badge(t.status,statusTone(t.status))}</td>
<td><button class="button secondary small" data-v522-edit-term="${t.id}">Edit Terms</button></td></tr>`}

async function addService(data,ctx){
  const catalog=(await api('/api/service-catalog')).services;const existing=new Set(data.items.map(x=>x.catalog.code));const available=catalog.filter(x=>!existing.has(x.code));
  if(!available.length){toast('All catalog services are already on this client schedule');return;}
  const first=available[0];
  modal({title:`Add service — ${esc(data.tenant.name)}`,wide:true,body:`<form id="v522-add-form" class="form-grid">
    ${sel('Service','service_code',available.map(x=>[x.code,x.name]),first.code)}${f('Negotiated client price','client_price','number',dollars(first.standard_price_cents),'min="0" step="0.01" required')}
    ${sel('Billing cadence','cadence',[['monthly','Monthly'],['annual','Annual'],['one_time','One-time / Project']],'monthly')}${f('Quantity','quantity','number','1','min="0.01" step="0.01" required')}
    ${f('RMR share %','rmr_share_pct','number',first.rmr_share_pct,'min="0" max="100" step="0.01" required')}${f('Step2 share %','step2_share_pct','number',first.step2_share_pct,'min="0" max="100" step="0.01" required')}
    ${sel('Split basis','split_basis',[['gross','Gross revenue'],['contribution','Contribution after direct cost']],'gross')}${f('Direct cost','direct_cost','number',dollars(first.direct_cost_cents),'min="0" step="0.01"')}
    ${sel('Originating organization','seller_org',[['RMR','RMR'],['Step2','Step2']],'RMR')}${f('Seller / relationship owner','seller_name','text',data.tenant.seller_name||'')}
    ${f('Effective date','effective_date','date',new Date().toISOString().slice(0,10),'required')}${sel('Status','status',[['active','Active'],['pending','Pending'],['inactive','Inactive']],'active')}${textarea('Commercial notes','notes','')}
  </form>`,footer:'<button class="button secondary" data-close-modal>Cancel</button><button class="button" id="v522-create-term">Add Service & Terms</button>',onOpen:(root,close)=>{
    const form=$('#v522-add-form',root);const service=form.service_code;
    service.addEventListener('change',()=>{const x=available.find(i=>i.code===service.value);form.client_price.value=dollars(x.standard_price_cents);form.rmr_share_pct.value=x.rmr_share_pct;form.step2_share_pct.value=x.step2_share_pct;form.direct_cost.value=dollars(x.direct_cost_cents)});
    $('#v522-create-term',root).addEventListener('click',async()=>{if(!form.reportValidity())return;try{await api(`/api/v522/admin/tenants/${data.tenant.id}/commercial-terms`,{method:'POST',body:termBody(form,true)});toast('Client service and commercial terms added');close();ctx.navigate('pricing')}catch(e){toast(e.message,'error')}})
  }});
}

function editTerm(item,ctx){const t=item.tenant_service,e=item.commercial_term||{},c=item.catalog,calc=item.calculation;modal({title:`Edit commercial terms — ${esc(c.name)}`,wide:true,body:`
  <div class="premium-alert"><strong>Client-specific terms</strong><span>Standard catalog price: ${money(c.standard_price_cents)}. Saving affects only ${esc(item.tenant.name)} and this service.</span></div>
  <form id="v522-edit-form" class="form-grid">
    ${f('Negotiated client price','client_price','number',dollars(t.contract_price_cents),'min="0" step="0.01" required')}${f('Usage price','usage_price','number',dollars(t.usage_price_cents),'min="0" step="0.01"')}
    ${sel('Billing cadence','cadence',[['monthly','Monthly'],['annual','Annual'],['one_time','One-time / Project']],t.cadence)}${f('Quantity','quantity','number',t.quantity,'min="0.01" step="0.01" required')}
    ${f('RMR share %','rmr_share_pct','number',calc.rmr_share_pct,'min="0" max="100" step="0.01" required')}${f('Step2 share %','step2_share_pct','number',calc.step2_share_pct,'min="0" max="100" step="0.01" required')}
    ${sel('Split basis','split_basis',[['gross','Gross revenue'],['contribution','Contribution after direct cost']],calc.split_basis)}${f('Direct cost','direct_cost','number',dollars(e.direct_cost_cents??c.direct_cost_cents),'min="0" step="0.01"')}
    ${sel('Originating organization','seller_org',[['RMR','RMR'],['Step2','Step2']],e.seller_org||item.tenant.seller_org||'RMR')}${f('Seller / relationship owner','seller_name','text',e.seller_name||item.tenant.seller_name||'')}
    ${f('Effective date','effective_date','date',String(t.effective_date||'').slice(0,10),'required')}${sel('Status','status',[['active','Active'],['pending','Pending'],['inactive','Inactive']],t.status)}${textarea('Commercial notes','notes',e.notes||t.notes||'')}
  </form>`,footer:'<button class="button secondary" data-close-modal>Cancel</button><button class="button" id="v522-save-term">Save Client Terms</button>',onOpen:(root,close)=>$('#v522-save-term',root).addEventListener('click',async()=>{const form=$('#v522-edit-form',root);if(!form.reportValidity())return;try{await api(`/api/v522/admin/tenants/${item.tenant.id}/commercial-terms/${t.id}`,{method:'PATCH',body:termBody(form,false)});toast('Client-specific commercial terms saved');close();ctx.navigate('pricing')}catch(err){toast(err.message,'error')}})});}
function termBody(form,includeService){const body={contract_price_cents:cents(form.client_price.value),usage_price_cents:cents(form.usage_price?.value||0),cadence:form.cadence.value,status:form.status.value,quantity:Number(form.quantity.value),effective_date:form.effective_date.value,rmr_share_pct:Number(form.rmr_share_pct.value),step2_share_pct:Number(form.step2_share_pct.value),split_basis:form.split_basis.value,direct_cost_cents:cents(form.direct_cost.value),seller_org:form.seller_org.value,seller_name:form.seller_name.value,notes:form.notes.value};if(includeService)body.service_code=form.service_code.value;return body}

async function economics(page,ctx){const data=await api('/api/v522/admin/partner-economics');const s=data.summary;page.innerHTML=`${pageHead('Partner Economics','Trace RMR and Step2 economics back to each client service agreement.',`<button class="button secondary" id="v522-open-pricing">Manage Client Terms</button>`)}
  ${s.unreviewed_defaults?`<div class="premium-alert warn"><strong>${s.unreviewed_defaults} active service${s.unreviewed_defaults===1?'':'s'} still use catalog defaults.</strong><span>Review them in Client Pricing before relying on settlement values.</span></div>`:''}
  <div class="premium-kpis">${kpi('Monthly Revenue',money(s.monthly_revenue_cents),'Configured client service schedules')}${kpi('Direct Costs',money(s.monthly_direct_cost_cents),'Configured by service')}${kpi('Contribution',money(s.monthly_contribution_cents),'Revenue less direct cost')}${kpi('RMR Share',money(s.rmr_share_cents),'Based on each service split')}${kpi('Step2 Share',money(s.step2_share_cents),'Based on each service split')}${kpi('Reconciliation',money(s.split_reconciliation_difference_cents),s.split_reconciliation_difference_cents?'Review required':'Split bases reconcile')}</div>
  <section class="premium-panel formula-panel"><header><div><h2>How the calculations work</h2><p>${esc(data.data_provenance)}</p></div></header><div class="formula-grid"><div><strong>Gross split</strong><span>${esc(data.formula.gross)}</span></div><div><strong>Contribution split</strong><span>${esc(data.formula.contribution)}</span></div><div><strong>Monthlyization</strong><span>${esc(data.formula.monthlyization)}</span></div></div></section>
  <section class="premium-panel"><header><div><h2>Client and Service Trace</h2><p>Open any row to see the exact terms and history behind the calculation.</p></div></header><div class="premium-table-wrap"><table class="premium-table"><thead><tr><th>Client</th><th>Service</th><th>Revenue</th><th>Direct Cost</th><th>Contribution</th><th>Basis</th><th>RMR</th><th>Step2</th><th>Terms Source</th><th></th></tr></thead><tbody>${data.items.filter(x=>x.tenant_service.status==='active').map(economicRow).join('')}</tbody></table></div></section>
  <section class="premium-panel"><header><div><h2>Revenue by Service</h2><p>Portfolio roll-up from the detailed client agreements above.</p></div></header><div class="premium-table-wrap"><table class="premium-table"><thead><tr><th>Service</th><th>Clients</th><th>Revenue</th><th>Direct Cost</th><th>Contribution</th><th>RMR</th><th>Step2</th></tr></thead><tbody>${data.by_service.map(x=>`<tr><td><strong>${esc(x.service_name)}</strong></td><td>${number(x.client_count)}</td><td>${money(x.monthly_revenue_cents)}</td><td>${money(x.monthly_direct_cost_cents)}</td><td>${money(x.monthly_contribution_cents)}</td><td>${money(x.rmr_share_cents)}</td><td>${money(x.step2_share_cents)}</td></tr>`).join('')}</tbody></table></div></section>`;
  $('#v522-open-pricing').addEventListener('click',()=>ctx.navigate('pricing'));$$('[data-v522-econ-detail]').forEach(btn=>btn.addEventListener('click',()=>economicsDetail(btn.dataset.v522EconDetail)));
}
function economicRow(item){const c=item.calculation;return `<tr><td><strong>${esc(item.tenant.name)}</strong></td><td>${esc(item.catalog.name)}</td><td>${money(c.monthly_revenue_cents)}</td><td>${money(c.monthly_direct_cost_cents)}</td><td>${money(c.monthly_contribution_cents)}</td><td>${esc(c.split_basis)}</td><td>${money(c.rmr_share_cents)}<small>${pct(c.rmr_share_pct)}</small></td><td>${money(c.step2_share_cents)}<small>${pct(c.step2_share_pct)}</small></td><td>${esc(item.terms_source)}</td><td><button class="button secondary small" data-v522-econ-detail="${item.tenant_service.id}">Explain</button></td></tr>`}
async function economicsDetail(id){try{const data=await api(`/api/v522/admin/partner-economics/terms/${id}`);const item=data.item,c=item.calculation;modal({title:`Calculation — ${esc(item.tenant.name)} / ${esc(item.catalog.name)}`,wide:true,body:`<div class="premium-kpis compact">${kpi('Revenue',money(c.monthly_revenue_cents),'Monthlyized client price')}${kpi('Direct Cost',money(c.monthly_direct_cost_cents),'Configured service cost')}${kpi('Split Base',money(c.split_base_cents),c.split_basis)}${kpi('RMR',money(c.rmr_share_cents),pct(c.rmr_share_pct))}${kpi('Step2',money(c.step2_share_cents),pct(c.step2_share_pct))}</div><div class="premium-alert ${c.reconciles?'success':'warn'}"><strong>${c.reconciles?'Calculation reconciles':'Calculation needs review'}</strong><span>RMR + Step2 ${c.reconciles?'equals':'does not equal'} the configured split base.</span></div><section class="premium-panel"><header><div><h2>Term history</h2><p>Saved versions are retained for traceability.</p></div></header>${data.history.length?`<div class="premium-table-wrap"><table class="premium-table"><thead><tr><th>Version</th><th>Changed</th><th>RMR</th><th>Step2</th><th>Price</th></tr></thead><tbody>${data.history.map(h=>`<tr><td>${h.version_number}</td><td>${new Date(h.created_at).toLocaleString()}</td><td>${pct(h.snapshot_json.commercial_term.rmr_share_pct)}</td><td>${pct(h.snapshot_json.commercial_term.step2_share_pct)}</td><td>${money(h.snapshot_json.tenant_service.contract_price_cents)}</td></tr>`).join('')}</tbody></table></div>`:'<p class="muted">No saved history yet; this row is using catalog defaults.</p>'}</section>`,footer:'<button class="button" data-close-modal>Done</button>'})}catch(e){toast(e.message,'error')}}
