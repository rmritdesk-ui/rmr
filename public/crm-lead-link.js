import {state} from './state.js';

// Focus only records returned by RMR's normal tenant/assignment/team-filtered API.
export function focusCrmLead(rows) {
  const id=state.routeQuery?.lead;
  if(!id) return null;
  const valid=/^[a-f0-9-]{36}$/i.test(id) && state.routeQuery.tenant===state.selectedTenantId;
  return {rows:valid?rows.filter(row=>row.id===id):[]};
}
export function showCrmLeadFocus(page,focus) {
  if(!focus) return;
  const section=document.createElement('section');
  section.className='card';
  section.setAttribute('aria-label','Requested CRM Lead');
  const title=document.createElement('h3');
  title.textContent=focus.rows.length?'Requested CRM Lead':'CRM lead unavailable in this authorized workspace';
  section.append(title);
  if(focus.rows.length) {
    const text=document.createElement('p');
    text.style.whiteSpace='pre-wrap';
    text.textContent=focus.rows[0].notes || 'No notes recorded.';
    section.append(text);
  }
  page.prepend(section);
}
