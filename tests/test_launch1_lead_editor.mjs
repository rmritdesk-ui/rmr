import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source=readFileSync(new URL('../public/pages/v53_client_experience.js',import.meta.url),'utf8');
const code=source.slice(source.indexOf('function editLeadModal('),source.indexOf('function convertLeadModal('));

test('lead editor submits four existing fields and returns to reloaded CRM list',async()=>{
  let options,save; const requests=[],navigation=[]; let closed=0;
  const values={company_name:'New Company',contact_name:'New Person',email:'new@example.invalid',phone:'+1 555 0100'};
  const form={reportValidity:()=>true,elements:{namedItem:name=>({value:values[name]})}};
  const $=selector=>selector==='#v53-save-lead'?{addEventListener:(_,fn)=>{save=fn;}}:form;
  const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;');
  const edit=new Function('$','modal','esc','api','toast',code+';return editLeadModal;')(
    $,o=>{options=o;},esc,async(...args)=>requests.push(args),()=>{});
  edit({id:'lead-1',company_name:'<unsafe " value'}, {navigate:path=>navigation.push(path)},()=>closed++);
  assert.match(options.body,/&lt;unsafe &quot; value/);
  for(const name of Object.keys(values))assert.ok(options.body.includes(`name="${name}"`));
  options.onOpen({},()=>closed++);await save();
  assert.deepEqual(requests,[['/api/v53/leads/lead-1',{method:'PATCH',body:values}]]);
  assert.deepEqual(navigation,['crm?tab=leads']);assert.equal(closed,2);
  form.reportValidity=()=>false;await save();assert.equal(requests.length,1);
  assert.match(source,/data-record-action="edit-lead"/);
  assert.match(source,/action==='edit-lead'\) editLeadModal\(r,ctx,close\)/);
});
