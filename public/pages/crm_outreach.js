import {api} from "../api.js";
import {$, esc, modal, toast} from "../ui.js";
import {state} from "../state.js";

export function composeUrl(provider, email, subject, body) {
  const local=email.split("@")[0];
  if(email.length>254||!/^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$/.test(email)||
     local.startsWith(".")||local.endsWith(".")||local.includes(".."))throw new Error("Add a valid contact email first.");
  if(/[\r\n]/.test(subject))throw new Error("Subject must be a single line.");
  const e=encodeURIComponent;
  const url=provider==="gmail"?`https://mail.google.com/mail/?view=cm&fs=1&to=${e(email)}&su=${e(subject)}&body=${e(body)}`:
    provider==="outlook"?`https://outlook.office.com/mail/deeplink/compose?to=${e(email)}&subject=${e(subject)}&body=${e(body)}`:
    `mailto:${e(email)}?subject=${e(subject)}&body=${e(body)}`;
  if(url.length>1800)throw new Error("This draft is too long for a reliable compose link. Shorten it, or copy the subject and message below into your email app.");
  return url;
}
export function phoneHref(phone) {
  const value=String(phone||"").trim();
  return /^\+?[\d ().-]+$/.test(value)&&/\d/.test(value)?`tel:${value.replace(/[ ().-]/g,"")}`:null;
}
function confirmationId() {
  if(crypto.randomUUID)return crypto.randomUUID();
  const bytes=crypto.getRandomValues(new Uint8Array(16));
  bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
  const hex=Array.from(bytes,b=>b.toString(16).padStart(2,"0")).join("");
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
export async function openProspectOutreach(row,ctx,editContact) {
  const tenant=state.selectedTenantId;
  try {
    const data=await api(`/api/prospects/${row.id}/outreach`);
    if(tenant!==state.selectedTenantId||data.tenant_id!==tenant)return;
    const phone=phoneHref(data.phone);
    const isEmail=Boolean(data.email);
    const confirmationLabel=isEmail?"Yes, I've Sent the Email":"Yes, I've Made the Call";
    modal({
      title:"Email Prospect",
      body:`<div class="crm-email-flow">
        <div class="crm-email-identity"><div><strong>${esc(row.contact_name||row.account_name||"Prospect")}</strong>
          ${row.contact_name&&row.account_name?`<p>${esc(row.account_name)}</p>`:""}</div><span class="v53-pill blue">Prospecting</span></div>
        ${data.invalid_email?'<p class="v53-dialog-note">The stored email is invalid. Update contact information to prepare an email.</p>':""}
        ${isEmail?`<section class="section-block"><h3>Prepare Introduction</h3>
          <p class="crm-email-recipient"><strong>To</strong> ${esc(data.email)}</p>
          <div class="field"><label for="outreach-subject">Subject</label><input id="outreach-subject" value="${esc(data.subject)}"></div>
          <div class="field"><label for="outreach-body">Message</label><textarea id="outreach-body" rows="6">${esc(data.body)}</textarea></div></section>
          <section class="section-block"><h3>Open Email Draft</h3>
          <p>Choose your email app, check your sending account, and send manually. Opening a draft does not send it.</p>
          <div class="crm-email-actions"><button class="button" data-compose="gmail">Open in Gmail</button>
          <button class="button secondary" data-compose="outlook">Outlook</button>
          <button class="button secondary" data-compose="mailto">Default Email App</button></div></section>`:
          data.phone?`<section class="section-block"><h3>Phone Contact Required</h3><p class="crm-email-phone">${esc(data.phone)}</p>
            ${phone?`<a class="button" id="outreach-call" href="${esc(phone)}">Call Prospect</a><p>Make the call in your phone app, then return here to confirm.</p>`:
              "<p>Update the phone number to a dialable format, or copy it to your phone.</p>"}</section>`:
          '<section class="section-block"><h3>Contact Information Needed</h3><p>Add a valid email address or phone number to contact this prospect.</p></section>'}
        <section id="outreach-confirmation" class="notice-card" aria-labelledby="outreach-confirm-heading" hidden>
          <h3 id="outreach-confirm-heading">${isEmail?"Did you send this email?":"Did you make the call?"}</h3>
          <p>${isEmail?"After sending the email from your email app, return here to confirm.":"After making the call, return here to confirm."}</p>
          <p>This is your manual confirmation, not verified delivery. The Prospect stays in Prospecting.</p>
          <div class="crm-email-actions"><button class="button" id="outreach-record" disabled>${confirmationLabel}</button>
          <button class="button secondary" id="outreach-not-yet">Not Yet</button></div>
        </section>
        <p id="outreach-status" role="status" aria-live="polite" tabindex="-1"></p>
        ${data.contact?'<button class="text-button" id="outreach-edit-contact">Edit Contact Information</button>':
          '<p>No linked Contact exists. Add contact information in CRM Contacts; the missing Prospect contact link also needs repair.</p><button class="text-button" id="outreach-contacts">Add/Edit Contact Information</button>'}
        </div>`,
      footer:'<button class="button secondary" data-close-modal>Close</button>',
      onOpen:(root,close)=>{
        let pending=false,recorded=false,submission=null,attempted=false;
        const sameTenant=()=>{if(state.selectedTenantId!==tenant)throw new Error("Client changed. Close and reopen Email.");};
        const confirm=$("#outreach-confirmation",root),record=$("#outreach-record",root),status=$("#outreach-status",root);
        const reveal=()=>{
          if(pending||recorded)return;
          attempted=true;confirm.hidden=false;record.disabled=false;status.textContent="";
          record.focus({preventScroll:true});
          confirm.scrollIntoView({block:"nearest"});
        };
        root.querySelectorAll("[data-compose]").forEach(button=>button.addEventListener("click",()=>{
          try {
            sameTenant();
            const url=composeUrl(button.dataset.compose,data.email,$("#outreach-subject",root).value,$("#outreach-body",root).value);
            if(button.dataset.compose==="mailto")window.location.href=url;
            else {
              const popup=window.open("about:blank","_blank");
              if(!popup)throw new Error("Popup blocked. Allow popups and retry, or use Open Default Email App.");
              popup.opener=null;popup.location.href=url;
            }
            reveal();
          }catch(e){$("#outreach-status",root).textContent=e.message;}
        }));
        $("#outreach-call",root)?.addEventListener("click",e=>{
          try{sameTenant();reveal();}catch(error){e.preventDefault();status.textContent=error.message;}
        });
        $("#outreach-not-yet",root).addEventListener("click",()=>{
          if(pending||recorded||submission)return;
          attempted=false;confirm.hidden=true;record.disabled=true;
          status.textContent="Nothing recorded. Your draft is still here when you are ready.";
          (root.querySelector("[data-compose]")||$("#outreach-call",root))?.focus();
        });
        $("#outreach-edit-contact",root)?.addEventListener("click",()=>{
          try{sameTenant();editContact(data.contact,close);}catch(e){$("#outreach-status",root).textContent=e.message;}
        });
        $("#outreach-contacts",root)?.addEventListener("click",()=>{close();ctx.navigate("crm?tab=contacts");});
        $("#outreach-record",root).addEventListener("click",async()=>{
          if(pending||recorded||!attempted)return;
          try {
            sameTenant();
            // Freeze the request across uncertain network retries.
            submission ||= {request_id:confirmationId(),method:isEmail?"Email":"Phone",note:"",confirmed:true};
            pending=true;record.disabled=true;record.textContent="Recording…";
            $("#outreach-not-yet",root).disabled=true;
            root.querySelectorAll("[data-close-modal]").forEach(button=>{button.disabled=true;});
            await api(`/api/prospects/${row.id}/contacted`,{method:"POST",body:submission});
            recorded=true;
            confirm.hidden=true;
            status.textContent=`${isEmail?"Email":"Phone contact"} recorded based on your confirmation. Prospect stage unchanged.`;
            status.focus({preventScroll:true});
            root.querySelectorAll("[data-compose],#outreach-call").forEach(control=>{
              control.disabled=true;control.setAttribute("aria-disabled","true");control.removeAttribute("href");
            });
          }catch(e){
            $("#outreach-status",root).textContent=e.message+(submission?" Retry uses the same confirmation to avoid duplicates.":"");
          }finally{
            pending=false;record.disabled=recorded;
            record.textContent=recorded?"Contact Recorded":submission?"Retry Confirmation":confirmationLabel;
            root.querySelectorAll("[data-close-modal]").forEach(button=>{button.disabled=false;});
          }
        });
        const dialog=root.querySelector(".modal");
        dialog.setAttribute("aria-label","Email Prospect");
        dialog.addEventListener("keydown",event=>{
          if(event.key==="Escape"){event.preventDefault();if(!pending)close();return;}
          if(event.key!=="Tab")return;
          const controls=[...dialog.querySelectorAll("button,a[href],input,textarea,select,[tabindex='0']")]
            .filter(el=>!el.disabled&&el.getClientRects().length);
          const first=controls[0],last=controls[controls.length-1];
          if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
          else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
        });
        ($("#outreach-subject",root)||$("#outreach-call",root)||$("#outreach-edit-contact",root)||$("#outreach-contacts",root))?.focus({preventScroll:true});
      },
    });
  }catch(e){toast(e.message,"error");}
}
