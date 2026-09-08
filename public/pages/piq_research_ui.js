import {api} from '../api.js';
import {researchMessage} from './piq_workflow_ui.js';
import {state} from '../state.js';
import {esc, modal, toast} from '../ui.js';

const messages = {
  awaiting_confirmation:'Research awaiting confirmation.', expired:'Research confirmation expired.',
  queued:'Adaptive Research queued…', running:'Researching additional public evidence…',
  retry_wait:'Research provider temporarily unavailable. Retrying…', completed:'Adaptive Research completed.',
  no_evidence:'Research completed with no accepted evidence.', partial:'Research completed with partial results.',
  failed:'Adaptive Research could not be completed.', cancelled:'Adaptive Research was cancelled.'
};
const active = new Set(['queued','running','retry_wait']);
const pending = new Set();
const monitors = new Map();
const identity = () => `${state.user?.id||''}:${state.selectedTenantId||state.user?.tenant_id||''}:${sessionStorage.getItem('rmr_managed_session')||''}`;
const keyFor = id => `rmr-piq-research:${identity()}:${id}`;
const save = (key, data) => {try {sessionStorage.setItem(key, JSON.stringify(data));}catch{}};
const forget = key => {try {sessionStorage.removeItem(key);}catch{}};
const read = key => {try {return JSON.parse(sessionStorage.getItem(key));}catch{return null;}};
const usd = value => `$${(Number(value)/1000000).toFixed(6)}`;
const call = (url, options={}) => api(url,{...options,signal:AbortSignal.timeout(15000)});

function monitor(id, runId, ctx, key) {
  monitors.get(key)?.();
  const page=document.querySelector('#page'), owner=identity();
  if(!page)return;
  const notice=document.createElement('div');notice.className='notice-card';notice.setAttribute('role','status');
  notice.dataset.piqResearchStatus='queued';notice.textContent=messages.queued;page.prepend(notice);
  let stopped=false,timer=null,failures=0;const deadline=Date.now()+300000;
  const current=()=>!stopped&&notice.isConnected&&state.route==='piq'&&owner===identity();
  function stop(){stopped=true;clearTimeout(timer);observer.disconnect();if(monitors.get(key)===stop)monitors.delete(key);}
  const observer=new MutationObserver(()=>{if(!current())stop();});observer.observe(document.body,{childList:true,subtree:true});
  monitors.set(key,stop);
  async function poll(){
    if(!current()){stop();return;}
    try{
      const result=await call(`/api/piq/${encodeURIComponent(id)}/adaptive-research/${encodeURIComponent(runId)}`);
      if(!current())return;
      if(result.run_id!==runId||!Object.hasOwn(messages,result.status))throw new Error('Invalid research state');
      const message=result.status==='no_evidence'?researchMessage(result):messages[result.status];
      failures=0;notice.dataset.piqResearchStatus=result.status;notice.textContent=message;
      if(!active.has(result.status)){
        forget(key);stop();toast(message,result.status==='failed'?'error':'success');
        if(['completed','no_evidence','partial'].includes(result.status))ctx.navigate('piq');
        return;
      }
    }catch(error){
      if(!current())return;
      failures++;
      if([401,403,404].includes(error.status)) {forget(key);stop();notice.textContent='Research status is unavailable for this session.';return;}
      if(failures>=3){stop();notice.textContent='Research status could not be refreshed. Return to ProspectIQ to check again.';return;}
    }
    if(Date.now()>=deadline){stop();notice.textContent='Research is taking longer than expected. Return to ProspectIQ to check again.';return;}
    timer=setTimeout(poll,3000);
  }
  timer=setTimeout(poll,3000);
}

export function restoreResearch(ctx,opportunities=[]) {
  for(const row of opportunities){
    const run=row.research?.latest;
    if(run&&active.has(run.status))save(keyFor(row.id),{id:row.id,runId:run.run_id});
  }
  const prefix=`rmr-piq-research:${identity()}:`;
  try{for(const key of Object.keys(sessionStorage)){
    if(key.startsWith(prefix)) {const record=read(key);if(record?.id&&record?.runId)monitor(record.id,record.runId,ctx,key);}
  }}catch{}
}

export async function startResearch(id,ctx,closeDetail=()=>{}) {
  const key=keyFor(id),owner=identity();
  if(pending.has(key))return;
  const saved=read(key);
  if(saved?.runId){closeDetail();monitor(id,saved.runId,ctx,key);return;}
  pending.add(key);
  toast('Estimating Adaptive Research…');
  const current=()=>owner===identity()&&state.route==='piq';
  try{
    const estimate=await call(`/api/piq/${encodeURIComponent(id)}/adaptive-research/estimate`,{method:'POST',body:{}});
    if(!current())return;
    if(estimate.provider_mode==='demonstration'){
      const result=await call(`/api/piq/${encodeURIComponent(id)}/adaptive-research`,{method:'POST',body:{}});
      if(current()){toast(`Research completed in ${result.provider_mode} mode`);closeDetail();ctx.navigate('piq');}
      return;
    }
    if(!estimate.run_id||!estimate.confirmation_token||!Number.isInteger(estimate.estimated_cost_microusd)||!Number.isInteger(estimate.maximum_cost_microusd))throw new Error('Invalid estimate');
    closeDetail();
    modal({title:'Adaptive Research',body:`<p>Research awaiting confirmation.</p><p>Estimated provider usage cost: <strong>${esc(usd(estimate.estimated_cost_microusd))}</strong></p><p>Maximum allowed: ${esc(usd(estimate.maximum_cost_microusd))}</p><p>This records operational provider usage, not a customer charge.</p><p>${esc(estimate.task_count)} research tasks · ${esc(estimate.model)}</p>${!estimate.can_confirm?'<p>Only a client administrator or authorized managed-write administrator can confirm live research.</p>':''}`,
      footer:`<button class="button secondary" data-close-modal>Cancel</button><button class="button" id="confirm-adaptive-research" ${estimate.can_confirm?'':'disabled'}>Confirm</button>`,
      onOpen:(root,close)=>root.querySelector('#confirm-adaptive-research').addEventListener('click',async event=>{
        if(pending.has(key)||!current())return;
        pending.add(key);event.target.disabled=true;
        // Save the known run ID BEFORE dispatch: a lost response can be reconciled
        // without replaying a spend confirmation or storing its nonce in storage.
        save(key,{id,runId:estimate.run_id});
        try{
          const result=await call(`/api/piq/${encodeURIComponent(id)}/adaptive-research`,{method:'POST',body:{run_id:estimate.run_id,confirmation_token:estimate.confirmation_token}});
          if(result.run_id!==estimate.run_id||!active.has(result.status))throw new Error('Invalid research response');
          if(current()){close();monitor(id,result.run_id,ctx,key);}
        }catch(error){
          if(error.status&&error.status<500)forget(key);
          if(current()){close();toast(error.status===409?'Research confirmation expired or changed. Request a new estimate.':'Research could not be started. Return to ProspectIQ to check its status.','error');if(read(key))monitor(id,estimate.run_id,ctx,key);}
        }finally{pending.delete(key);}
      })});
  }catch{if(current())toast('Adaptive Research is unavailable. Check access, research configuration, and the cost limit.','error');}
  finally{pending.delete(key);}
}
