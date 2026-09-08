
from __future__ import annotations
import re
CARD_RE=re.compile(r'(?<!\d)(?:\d[ -]*?){13,19}(?!\d)')
SSN_RE=re.compile(r'(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)')
SECRET_RE=re.compile(r'(?i)\b(password|api[_ -]?key|secret|private[_ -]?key|cvv|cvc)\b\s*[:=]')
PHI_RE=re.compile(r'(?i)\b(patient|diagnosis|medical record|protected health information|hipaa)\b')
def luhn(s):
    ds=[int(x) for x in re.sub(r'\D','',s)]
    if not 13<=len(ds)<=19: return False
    total=0; parity=len(ds)%2
    for i,d in enumerate(ds):
        if i%2==parity: d*=2; d=d-9 if d>9 else d
        total+=d
    return total%10==0
def scan_text(text):
    text=str(text or ''); findings=[]
    for m in CARD_RE.finditer(text):
        if luhn(m.group()): findings.append({'type':'FULL_PAYMENT_CARD','severity':'BLOCK'})
    if SSN_RE.search(text): findings.append({'type':'SOCIAL_SECURITY_NUMBER','severity':'WARN'})
    if SECRET_RE.search(text): findings.append({'type':'CREDENTIAL_OR_SECRET','severity':'BLOCK'})
    if PHI_RE.search(text): findings.append({'type':'POSSIBLE_PHI','severity':'WARN'})
    return findings
POLICY={'full_card_data':'PROHIBITED','cvv_cvc':'PROHIBITED','hipaa_phi':'PROHIBITED_BY_DEFAULT','bulk_ssn':'PROHIBITED_BY_DEFAULT','biometric':'PROHIBITED_BY_DEFAULT','children_data':'PROHIBITED_BY_DEFAULT','credentials_in_notes':'PROHIBITED','regulated_high_impact_decisions':'PROHIBITED_WITHOUT_SEPARATE_APPROVAL'}
