import {esc} from "../ui.js";

// Source snapshot only: never bind this section to editable CRM fields.
export function renderPiqIntelligence(data) {
  if(!data)return "";
  const list=items=>items?.length?`<ul>${items.map(item=>`<li>${esc(item)}</li>`).join("")}</ul>`:"<p>No items supplied in this snapshot.</p>";
  const links=items=>(items||[]).map(s=>{
    try {
      const u=new URL(s.url);
      if(!["http:","https:"].includes(u.protocol)||u.username||u.password)return "";
      return `<a href="${esc(u.href)}" target="_blank" rel="noopener noreferrer">${esc(s.title||u.hostname)}</a>`;
    }catch{return "";}
  }).filter(Boolean).join(" · ");
  const section=(name,body)=>`<details><summary>${name}</summary>${body}</details>`;
  const source=data.source||{};
  return `<section class="v53-detail-section v53-intelligence" aria-label="ProspectIQ Intelligence">
    <header><div><span class="v53-eyebrow">ProspectIQ Intelligence</span><h3>${esc(source.company_name||"ProspectIQ")}</h3></div>
    ${source.piq_score!=null?`<strong>${esc(source.piq_score)}/100</strong>`:""}</header>
    <p>${esc(data.verification)}</p>
    <dl>${[["Industry",source.industry],["Location",source.address],["Phone",source.phone],
      ["Contact",source.contact_name],["Email",source.email],["PIQ status",data.status],["PIQ ID",data.prospect_public_id],
      ["Source",data.source_name],["Source updated",data.source_updated_at],
      ["Transferred",data.transferred_at]].filter(([,v])=>v).map(([k,v])=>`<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")}
      ${data.website?`<dt>Website</dt><dd>${links([{url:data.website,title:data.website}])}</dd>`:""}</dl>
    ${data.source_url?`<p>Discovery source: ${links([{url:data.source_url}])}</p>`:""}
    ${(data.profile_matches||[]).map(p=>`<p>Target Profile: ${esc(p.profile_name)} <small>${esc(p.target_profile_id)}</small></p>`).join("")}
    ${section("Verified",list(data.verified))}
    ${section("Needs Validation",list(data.needs_validation))}
    ${section("Adaptive Research Results",(data.research_runs||[]).map(r=>`<p>${esc(r.status)} · ${esc(r.completed_at||"Not completed")}</p>`).join("")+
      ((data.research_results||[]).map(r=>`<article><h4>${esc(r.label)} — ${esc(r.status.replaceAll("_"," "))}</h4><p>${esc(r.explanation)}</p>${r.caveat?`<p>${esc(r.caveat)}</p>`:""}<p>${links(r.sources)}</p></article>`).join("")||"<p>No research outcomes supplied.</p>"))}
    ${section("Supporting source evidence",(data.research_evidence||[]).map(r=>`<article><strong>${esc(r.claim)}</strong><p>${esc(r.explanation)}</p><p>${links(r.sources)}</p></article>`).join("")||"<p>No source evidence supplied.</p>")}
    ${section("Why this matched",list(data.why_this_matched))}
    ${data.recommended_next_step?`<h4>Recommended next step</h4><p>${esc(data.recommended_next_step)}</p>`:""}
    <small>${esc(data.note)}</small>
  </section>`;
}
