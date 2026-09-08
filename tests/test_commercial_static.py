
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
def test_commercial_files_present():
    needed=['rmr_platform/commercial/router.py','rmr_platform/commercial/providers.py','rmr_platform/commercial/security.py','static/commercial-console.html']
    assert all((ROOT/x).exists() for x in needed)
def test_no_social_provider_oauth_in_launch_scope():
    s=(ROOT/'static/commercial-console.html').read_text();assert 'COPY_PASTE' in s or 'copy/paste' in s.lower()
def test_email_provider_adapters_present():
    s=(ROOT/'rmr_platform/commercial/providers.py').read_text();assert all(x in s for x in ['MicrosoftGraphAdapter','GoogleGmailAdapter','SMTPIMAPAdapter'])
def test_secure_data_custody_access_present():
    s=(ROOT/'rmr_platform/commercial/router.py').read_text();assert 'RMR Owner Secure Tenant Access' in s and 'secure-access/start' in s and "mode='READ_ONLY'" in s
def test_human_approval_gate_present():
    s=(ROOT/'rmr_platform/commercial/router.py').read_text();assert 'Human approval is required before sending' in s
@pytest.mark.legacy_packaging
def test_legacy_product_owner_launcher_present():
    assert (ROOT/'START-PRODUCT-OWNER-TEST.bat').is_file()

@pytest.mark.legacy_packaging
def test_frozen_baseline_embedded():
    assert any((ROOT/'control'/'frozen-baseline').glob('*FROZEN_ACCEPTED*.zip'))
