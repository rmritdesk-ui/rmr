import {api} from '../api.js';
import {state} from '../state.js';
import {$, esc, modal} from '../ui.js';

export const CRM_IMPORT_LIMIT = 500;
export const CRM_IMPORT_BYTES = 1024 * 1024;
const FIELDS = [['company_name','Company (required)'],['contact_name','Contact name'],['email','Email'],['phone','Phone']];

// CSV quoting (including escaped quotes/newlines); tabs outside quotes select TSV.
export function parseCrmImport(text) {
  if(new TextEncoder().encode(text).length > CRM_IMPORT_BYTES)throw new Error('Use a file or paste smaller than 1 MiB.');
  text=String(text).replace(/^\uFEFF/,'');
  let quoted=false,delimiter=',';
  for(let i=0;i<text.length;i++){
    if(text[i]==='"'){if(quoted&&text[i+1]==='"'){i++;continue;}quoted=!quoted;}
    if(!quoted&&text[i]==='\t'){delimiter='\t';break;}
    if(!quoted&&/[\r\n]/.test(text[i]))break;
  }
  const rows=[];let row=[],value='',inQuotes=false,closed=false;
  const cell=()=>{row.push(value.trim());value='';closed=false;if(row.length>100)throw new Error('Use no more than 100 columns.');};
  const line=()=>{cell();if(row.some(Boolean))rows.push(row);row=[];if(rows.length>CRM_IMPORT_LIMIT+1)throw new Error('Import no more than 500 data rows at a time.');};
  for(let i=0;i<text.length;i++){
    const c=text[i];
    if(inQuotes){if(c==='"'){if(text[i+1]==='"'){value+='"';i++;}else{inQuotes=false;closed=true;}}else value+=c;continue;}
    if(c===delimiter){cell();continue;}
    if(c==='\n'||c==='\r'){if(c==='\r'&&text[i+1]==='\n')i++;line();continue;}
    if(c==='"'){if(value||closed)throw new Error('Invalid CSV quoting. Put quotes around the entire field.');inQuotes=true;continue;}
    if(closed){if(c===' '||c==='\t')continue;throw new Error('Unexpected text after a quoted CSV field.');}
    value+=c;
  }
  if(inQuotes)throw new Error('Unclosed quoted CSV field.');
  if(value||row.length||closed)line();
  if(!rows.length)throw new Error('Choose a CSV file or paste some rows first.');
  return rows;
}

export function mapCrmImport(rows,mapping,hasHeader=true){
  const data=hasHeader?rows.slice(1):rows;
  if(!data.length)throw new Error('No data rows found.');
  if(data.length>CRM_IMPORT_LIMIT)throw new Error('Import no more than 500 data rows at a time.');
  if(mapping.company_name===''||mapping.company_name===undefined)throw new Error('Map a Company column.');
  const columns=Object.values(mapping).filter(x=>x!==''&&x!==undefined).map(Number);
  if(new Set(columns).size!==columns.length)throw new Error('Map each column to only one field.');
  return data.map(row=>Object.fromEntries(FIELDS.map(([key])=>[key,mapping[key]===''||mapping[key]===undefined?'':row[Number(mapping[key])]||''])));
}

export function openCrmImport(ctx){
  const tenantId=state.selectedTenantId;
  modal({title:'Import CRM Leads',wide:true,
    body:`<p>Upload CSV or paste comma/tab-separated rows. Company is required. No Adaptive Research or purchase is needed. Limit: 500 data rows, 1 MiB.</p>
      <div class="form-grid"><div class="field full"><label>CSV file</label><input id="crm-file" type="file" accept=".csv,text/csv"></div>
      <div class="field full"><label>Or paste CSV / spreadsheet rows</label><textarea id="crm-paste" rows="5" placeholder="Company,Contact name,Email,Phone"></textarea></div>
      <div class="field full"><label><input id="crm-header" type="checkbox" checked> First row contains column headings</label></div></div>
      <button class="button secondary" id="crm-map">Map Columns</button><div id="crm-mapping"></div>
      <p role="status" id="crm-import-status"></p><div id="crm-import-preview" style="overflow:auto;max-height:340px"></div>`,
    footer:'<button class="button secondary" data-close-modal>Close</button><button class="button secondary" id="crm-preview" disabled>Preview</button><button class="button" id="crm-commit" disabled>Import Ready Rows</button>',
    onOpen:(root)=>{
      let parsed=[],prepared=null,filename='pasted-list.csv',busy=false,done=false;
      const status=$('#crm-import-status',root),preview=$('#crm-preview',root),commit=$('#crm-commit',root);
      const ensureTenant=()=>{if(state.selectedTenantId!==tenantId)throw new Error('Client changed. Close and reopen Import for the selected client.');};
      const invalidate=()=>{prepared=null;commit.disabled=true;$('#crm-import-preview',root).innerHTML='';};
      const reset=()=>{if(busy||done)return;invalidate();parsed=[];preview.disabled=true;$('#crm-mapping',root).innerHTML='';status.textContent='';};
      const setBusy=value=>{busy=value;root.querySelectorAll('input,textarea,select,#crm-map').forEach(el=>el.disabled=value||done);preview.disabled=value||done||!parsed.length;commit.disabled=true;};
      $('#crm-file',root).addEventListener('change',()=>{$('#crm-paste',root).value='';reset();});
      $('#crm-paste',root).addEventListener('input',()=>{$('#crm-file',root).value='';reset();});
      $('#crm-header',root).addEventListener('change',reset);
      $('#crm-map',root).addEventListener('click',async()=>{
        if(busy||done)return;invalidate();setBusy(true);
        try{
          ensureTenant();const file=$('#crm-file',root).files[0];
          if(file&&(!/\.csv$/i.test(file.name)||file.size>CRM_IMPORT_BYTES))throw new Error('Choose a CSV file of at most 1 MiB.');
          filename=file?file.name.slice(0,255):'pasted-list.csv';
          parsed=parseCrmImport(file?await file.text():$('#crm-paste',root).value);
          const hasHeader=$('#crm-header',root).checked;
          const count=parsed.length-(hasHeader?1:0);
          if(count<1||count>CRM_IMPORT_LIMIT)throw new Error('Provide between 1 and 500 data rows.');
          const width=Math.max(...parsed.map(r=>r.length));
          const headers=Array.from({length:width},(_,i)=>hasHeader?(parsed[0][i]||`Column ${i+1}`):`Column ${i+1}`);
          const aliases={company_name:['company','companyname','business','businessname'],contact_name:['contact','contactname','name','fullname'],email:['email','emailaddress'],phone:['phone','phonenumber','telephone']};
          $('#crm-mapping',root).innerHTML=`<h3>Map columns</h3><div class="form-grid">${FIELDS.map(([key,label],index)=>{
            const guess=hasHeader?headers.findIndex(h=>aliases[key].includes(h.toLowerCase().replace(/[^a-z]/g,''))):index;
            return `<div class="field"><label>${label}</label><select data-import-field="${key}"><option value="">Not mapped</option>${headers.map((h,i)=>`<option value="${i}" ${i===guess?'selected':''}>${esc(h)} (column ${i+1})</option>`).join('')}</select></div>`;
          }).join('')}</div><p>Duplicates: existing account company, matching CRM email, or company + contact when no email is supplied. Duplicate rows in this input are skipped too.</p>`;
          root.querySelectorAll('[data-import-field]').forEach(el=>el.addEventListener('change',invalidate));
          status.textContent=`${count} data rows loaded. Check the mapping, then Preview.`;
        }catch(e){parsed=[];status.textContent=e.message;}finally{setBusy(false);}
      });
      preview.addEventListener('click',async()=>{
        if(busy||done)return;invalidate();setBusy(true);
        try{
          ensureTenant();const mapping=Object.fromEntries([...root.querySelectorAll('[data-import-field]')].map(el=>[el.dataset.importField,el.value]));
          const rows=mapCrmImport(parsed,mapping,$('#crm-header',root).checked);
          const result=await api(`/api/tenants/${tenantId}/crm/import-preview`,{method:'POST',body:{filename,rows}});
          prepared=rows;
          status.textContent=`${result.ready} ready · ${result.duplicates} duplicates/skipped · ${result.errors} invalid`;
          $('#crm-import-preview',root).innerHTML=`<table><thead><tr><th>Row</th><th>Company</th><th>Contact</th><th>Email</th><th>Phone</th><th>Status / reason</th></tr></thead><tbody>${result.preview.map(r=>`<tr><td>${r.row}</td><td>${esc(r.company_name)}</td><td>${esc(r.contact_name)}</td><td>${esc(r.email)}</td><td>${esc(r.phone)}</td><td>${esc([r.status,r.duplicate_reason,...r.errors].filter(Boolean).join(' — '))}</td></tr>`).join('')}</tbody></table>`;
          setBusy(false);commit.disabled=result.ready<1;return;
        }catch(e){status.textContent=e.message;}finally{if(busy)setBusy(false);}
      });
      commit.addEventListener('click',async()=>{
        if(busy||done||!prepared)return;setBusy(true);
        try{
          ensureTenant();const result=await api(`/api/tenants/${tenantId}/crm/import`,{method:'POST',body:{filename,rows:prepared}});
          done=true;prepared=null;
          status.textContent=`Imported ${result.created} lead(s). Skipped ${result.duplicates} duplicate(s) and ${result.errors} invalid row(s).`;
          const view=document.createElement('button');view.className='button secondary';view.textContent='View imported leads';
          view.addEventListener('click',()=>{root.querySelector('[data-close-modal]')?.click();ctx.navigate('crm?tab=leads');});status.after(view);
        }catch(e){status.textContent=`${e.message} Preview again before retrying.`;prepared=null;}finally{setBusy(false);}
      });
    }});
}
