import {api} from '../api.js';
import {state} from '../state.js';
import {esc, money, toast} from '../ui.js';

export const POLL_INTERVAL_MS = 3000;
export const POLL_TIMEOUT_MS = 300000;
const REQUEST_TIMEOUT_MS = 15000;
const TERMINAL = new Set(['completed','partial','failed','cancelled']);
const ACTIVE = new Set(['queued','running','retry_wait']);
const MESSAGES = {
  queued:'Discovery queued…', running:'Finding matching prospects…',
  retry_wait:'Provider temporarily unavailable. Retrying…', completed:'Discovery completed.',
  partial:'Discovery completed with partial results. Some provider requests could not be completed.',
  failed:'Discovery could not be completed.', cancelled:'Discovery was cancelled.'
};
let activeView = null;
const pendingSubmissions = new Map();
const memory = new Map();

function read(key) { try { return JSON.parse(sessionStorage.getItem(key)) || memory.get(key) || {}; } catch { return memory.get(key) || {}; } }
function save(key, value) { memory.set(key,value); try { sessionStorage.setItem(key,JSON.stringify(value)); } catch {} }
function clear(key) { memory.delete(key); try { sessionStorage.removeItem(key); } catch {} }

export function discoveryError(error) {
  if (error.status===401) return 'Your session has expired. Please sign in again.';
  if (error.status===403) return 'You do not have permission to run or view this discovery.';
  if (error.status===404) return 'This discovery run is no longer available.';
  if (error.status===400 || error.status===422) return 'Review your Target Profile and discovery request before trying again.';
  if (error.status===409) return 'This discovery request conflicts with a previous submission. Return to ProspectIQ to check its status.';
  if (error.status===503 || error.error_code==='invalid_configuration') return 'Live prospect discovery is not configured.';
  if (error.error_code==='provider_auth') return 'Prospect discovery provider authentication failed.';
  if (error.error_code==='provider_timeout') return 'Prospect discovery timed out. Please try again.';
  if (['provider_rate_limit','provider_5xx'].includes(error.error_code)) return 'Prospect discovery is temporarily unavailable. Please try again later.';
  return 'Prospect discovery could not be completed. Please try again later.';
}

/** One active view, one request at a time. Server run state is never invented. */
export function bindDiscovery({page, button, tenantId, refresh, demoMessage, profileId, requestedCount=()=>6, onRun=()=>{}}) {
  activeView?.();
  if (!button) return;
  const userId=state.user?.id;
  const key=`rmr_piq_discovery:${userId}:${tenantId}${profileId?':'+profileId:''}`;
  const notice=document.createElement('div');
  notice.className='notice-card'; notice.hidden=true; notice.setAttribute('role','status'); notice.setAttribute('aria-live','polite');
  notice.dataset.piqDiscoveryStatus=''; button.closest('section')?.after(notice);
  if (!notice.isConnected) page.prepend(notice);
  const originalLabel=button.textContent;
  let disposed=false, timer=null, abort=null, deadline=0, failures=0, checking=false;
  let record=read(key);
  const current=()=>!disposed && button.isConnected && state.selectedTenantId===tenantId && state.user?.id===userId && state.route==='piq';
  const busy=value=>{ if(current()) {button.disabled=value;button.textContent=value?'Discovery in progress…':originalLabel;} };
  const message=(value,status='')=>{if(current()){notice.hidden=false;notice.dataset.piqDiscoveryStatus=status;notice.textContent=value;}};
  function dispose() {
    disposed=true; clearTimeout(timer); abort?.abort(); observer.disconnect();
    window.removeEventListener('hashchange',leave); window.removeEventListener('pagehide',dispose);
    button.removeEventListener('click',submit);
    if(activeView===dispose) activeView=null;
  }
  function leave(){dispose();}
  const observer=new MutationObserver(()=>{if(!current())dispose();});
  observer.observe(document.body,{childList:true,subtree:true});
  window.addEventListener('hashchange',leave); window.addEventListener('pagehide',dispose);
  activeView=dispose;
  function pause(text) {
    clearTimeout(timer); message(text); busy(Boolean(record.runId));
    if(!current())return;
    const check=document.createElement('button'); check.className='button secondary small'; check.textContent='Check discovery status';
    check.addEventListener('click',()=>{check.disabled=true;deadline=Date.now()+POLL_TIMEOUT_MS;failures=0;restore();});
    notice.append(' ',check);
  }
  async function request(path) {
    abort=new AbortController();
    const timeout=setTimeout(()=>abort?.abort(),REQUEST_TIMEOUT_MS);
    try{return await api(path,{signal:abort.signal});}finally{clearTimeout(timeout);abort=null;}
  }
  function valid(run) {return run && typeof run.run_id==='string' && (ACTIVE.has(run.status)||TERMINAL.has(run.status));}
  async function accept(run) {
    if(!current())return;
    if(!valid(run) || (record.runId && record.runId!==run.run_id)) throw new Error('Invalid run response');
    record={runId:run.run_id,status:run.status};save(key,record);
    onRun(run);
    message(MESSAGES[run.status],run.status);
    if(TERMINAL.has(run.status)) {
      clearTimeout(timer);clear(key);record={};busy(false);
      const text=run.status==='failed'?discoveryError(run):MESSAGES[run.status];
      message(text,run.status);toast(text,['failed','partial'].includes(run.status)?'error':'success');
      if(['completed','partial'].includes(run.status)) await refresh();
    } else {busy(true);timer=setTimeout(poll,POLL_INTERVAL_MS);}
  }
  async function poll() {
    if(!current()||checking)return;
    if(Date.now()>=deadline){pause('Discovery is still processing. You can return to this page to check results.');return;}
    checking=true;
    try {
      const run=await request(`/api/tenants/${encodeURIComponent(tenantId)}/piq/discovery-runs/${encodeURIComponent(record.runId)}`);
      failures=0;await accept(run);
    } catch(error) {
      if(!current())return;
      if(error.status===404){clear(key);record={};busy(false);message(discoveryError(error));return;}
      if([401,403].includes(error.status)){message(discoveryError(error));return;}
      failures++;
      if(failures>=3){pause('Discovery status is temporarily unavailable. The run may still be processing.');return;}
      message('Connection interrupted. Checking discovery status again…');timer=setTimeout(poll,POLL_INTERVAL_MS);
    } finally {checking=false;}
  }
  async function restore() {
    if(!current()||checking)return;
    busy(true);
    if(pendingSubmissions.has(key))await pendingSubmissions.get(key);
    if(!current())return;
    record=read(key);deadline=Date.now()+POLL_TIMEOUT_MS;
    if(record.runId){await poll();return;}
    checking=true;
    try {
      const response=await request(`/api/tenants/${encodeURIComponent(tenantId)}/piq/discovery-runs/active${profileId?'?target_profile_id='+encodeURIComponent(profileId):''}`);
      if(!current())return;
      if(!response || !Object.hasOwn(response,'run'))throw new Error('Invalid active-run response');
      if(response.run)await accept(response.run);else busy(false);
    } catch(error) {
      if(!current())return;
      if([401,403].includes(error.status)){message(discoveryError(error));return;}
      pause('Unable to check for an existing discovery. Check status before submitting again.');busy(true);
    } finally {checking=false;}
  }
  async function submit() {
    if(!current()||button.disabled||record.runId||pendingSubmissions.has(key))return;
    let count;
    try{count=requestedCount();}catch(error){toast(error.message,'error');return;}
    busy(true);message('Submitting discovery…');
    record=read(key);
    const idempotencyKey=record.idempotencyKey || crypto.randomUUID?.() || Array.from(crypto.getRandomValues(new Uint8Array(16)),value=>value.toString(16).padStart(2,'0')).join('');
    record={idempotencyKey};save(key,record);
    // Keep submission alive across in-app navigation so its run ID is retained.
    const submission=api(`/api/tenants/${encodeURIComponent(tenantId)}/piq/discover`,{
      method:'POST',headers:{'Idempotency-Key':idempotencyKey},body:{count,...(profileId?{target_profile_id:profileId}:{})},signal:AbortSignal.timeout(REQUEST_TIMEOUT_MS)
    });
    const settled=submission.then(result=>{if(valid(result))save(key,{runId:result.run_id,status:result.status});else if(Array.isArray(result.created))clear(key);},()=>{});
    pendingSubmissions.set(key,settled);
    let reconcile=false;
    try {
      const result=await submission;await settled;
      if(!current())return;
      if(valid(result)){record={};deadline=Date.now()+POLL_TIMEOUT_MS;await accept(result);}
      else if(Array.isArray(result.created)){record={};toast(demoMessage(result));await refresh();}
      else throw new Error('Invalid discovery response');
    } catch(error) {
      if(current()){message(discoveryError(error));toast(discoveryError(error),'error');busy(false);}
      // Retain the idempotency key on uncertain transport failure; a retry cannot
      // silently create another run if the first request reached the server.
      if(error.status && error.status<500){clear(key);record={};reconcile=error.status===409;}
    } finally {
      pendingSubmissions.delete(key);
      if(reconcile&&current())restore();
      else if(current()&&!read(key).runId)busy(false);
    }
  }
  button.addEventListener('click',submit);
  restore();
  return dispose;
}

export const isLiveProspect = row => row.provider==='google_places';
export const providerLabel = row => isLiveProspect(row)?'Google Places':['demonstration','demo'].includes(row.provider)?'Demonstration':(row.provider==='import'||(!row.provider&&row.status==='Imported'))?'Imported':!row.provider?'Source not recorded':'Other source';
export const potentialLabel = row => isLiveProspect(row)&&!row.estimated_value_cents?'Not estimated':money(row.estimated_value_cents);
const percent=value=>Number.isFinite(value)?`${Math.max(0,Math.min(100,value))}%`:'Unknown';
export function fitLabel(row) {
  if(!isLiveProspect(row))return row.status||'Profile';
  return Number(row.evidence_completeness_pct)>0 && Number(row.confidence_score)>=50?
    'Discovered prospect — review profile evidence':'Discovered prospect — fit unverified';
}
export function liveDetails(row) {
  if(!isLiveProspect(row))return '';
  return `<div class="notice-card"><p>${esc(fitLabel(row))}</p><p>Base Match: ${esc(row.base_match_score)} · Research Adjustment: ${(row.adaptive_score_delta||0)>=0?'+':''}${esc(row.adaptive_score_delta||0)} · Final Match: ${esc(row.score)}</p><strong>Google Places · Match: ${esc(row.score)}</strong><p>Confidence: ${percent(row.confidence_score)} · Evidence completeness: ${percent(row.evidence_completeness_pct)}</p><p>Confidence describes evidence strength, not fit. Completeness covers assessable criteria only; employee count and revenue remain unknown in the discovery baseline. Research findings are shown separately.</p><p>Google Place ID: ${esc(row.source_external_id||'Not recorded')} · ${sourceLink(row.source_url,'Google source')}</p><p>Address: ${esc(row.location||'Unknown')}</p><p>Phone: ${esc(row.phone||'Unknown')} · Website: ${sourceLink(row.website,'Website')||'Unknown'}</p><p>Potential: ${potentialLabel(row)}</p></div>`;
}
export function matchDetails(match) {
  if(!match)return '<p>No structured discovery match is recorded for this prospect.</p>';
  const criteria=match.criteria_result_json?.criteria||[];
  const value=v=>v===null||v===undefined?'Unknown':typeof v==='object'?JSON.stringify(v):String(v);
  return `<section class="notice-card" data-piq-match-details><h3>Discovery match explanation</h3><p>${esc(match.explanation||'')}</p><p>Scoring version: ${esc(match.scoring_version||'Unknown')}</p><p>These are the original discovery criteria; accepted Adaptive Research evidence is shown separately below.</p>${criteria.map(c=>`<div class="list-item"><span class="grow"><strong>${esc(c.criterion)} · ${esc(c.state)}</strong><small>Target: ${esc(value(c.requested))} · Observed: ${esc(value(c.observed))}</small><p>${esc(c.reason||'')}</p><small>Base contribution: ${esc(c.score_effect??0)}</small></span></div>`).join('')}<p>Unresolved discovery criteria: ${esc(criteria.filter(c=>c.state==='unresolved').map(c=>c.criterion).join(', ')||'None recorded')}</p></section>`;
}
export function sourceLink(value,label='Source') {
  try {const url=new URL(value);if(!['https:','http:'].includes(url.protocol)||url.username||url.password)return '';return `<a href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`;}catch{return '';}
}
export function evidenceLabel(evidence) {
  if(!['google_places','openai_research'].includes(evidence.provider))return '';
  const label=({confirmed:'Confirmed · observed in source',inferred:'Inferred · not verified',unresolved:'Unresolved · not verified',contradicted:'Contradicted · source-backed conflict'})[evidence.evidence_state]||'Unresolved · not verified';
  const effect=Number.isInteger(evidence.score_effect)?` · Criterion effect: ${evidence.score_effect>=0?'+':''}${evidence.score_effect} (deduplicated and capped in the final adjustment)`:'';
  return `${evidence.provider==='openai_research'?'Adaptive Research evidence · ':'Discovery evidence · '}${esc(label)} · Criterion: ${esc(evidence.profile_criterion||'Not recorded')} · ${esc(evidence.source_domain||'')} ${sourceLink(evidence.source_url)}${esc(effect)}`;
}
