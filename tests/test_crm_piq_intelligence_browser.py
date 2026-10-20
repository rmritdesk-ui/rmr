from test_prospectiq_federation import federation_engine, fx
from test_prospectiq_crm import transfer
from test_launch1_crm_drip import app_client
from test_crm_import_browser import browser_page, playwright
from test_crm_piq_intelligence import rich_payload


def test_rich_handoff_detail_real_api_and_browser(browser_page, transfer, app_client):
    page, calls = browser_page
    data=rich_payload(transfer)
    data["prospect"]["intelligence_snapshot"]["research_results"][0]["sources"].append(
        {"url":"javascript:alert(1)","title":"Unsafe link"})
    result=transfer.call(data)
    assert result.status_code==201
    lead_id=result.json()["rmr_lead_id"]
    response=app_client.get(f"/api/v53/tenants/{transfer.f.a.id}/crm/records/lead/{lead_id}")
    assert response.status_code==200
    assert response.json()["piq_intelligence"]["source"]["piq_score"]==77
    denied=app_client.get(f"/api/v53/tenants/{transfer.f.b.id}/crm/records/lead/{lead_id}")
    assert denied.status_code in (403,404)
    page.get_by_text("Close",exact=True).click()
    page.locator('[data-crm-tab="pipeline"]').click()
    page.locator(f'[data-open-record="lead"][data-record-id="{lead_id}"]').click()
    section=page.locator('[aria-label="ProspectIQ Intelligence"]')
    playwright.expect(section).to_be_visible()
    playwright.expect(section).to_contain_text("77/100")
    section.get_by_text("Verified",exact=True).click()
    playwright.expect(section.get_by_text("Construction services",exact=True)).to_be_visible()
    section.get_by_text("Adaptive Research Results",exact=True).click()
    playwright.expect(section.get_by_text("Jane is the reported owner.",exact=True)).to_be_visible()
    playwright.expect(section.locator('a[href="https://example.invalid/team?id=1"]')).to_be_visible()
    playwright.expect(section.locator('a[href^="javascript:"]')).to_have_count(0)
    playwright.expect(section).to_contain_text("not found")
    playwright.expect(section).to_contain_text("Contact the owner")
    # No research content leaked into compact pipeline cards.
    assert "Jane is the reported owner" not in page.locator(".v53-pipeline-workspace").inner_text()
