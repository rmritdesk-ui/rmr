"""Read-only rendered UI checks with fully intercepted fake API data."""
import pytest
from playwright.sync_api import expect
from qa.test_piq_parity_browser import app
from qa.test_piq_phase3_browser import LIVE


@pytest.mark.parametrize('role',['CLIENT_ADMIN','SALES_REP'])
@pytest.mark.parametrize('kind,message',[
    ('no_findings','Research completed, but no supporting findings were returned.'),
    ('findings_rejected','Research completed, but the findings did not pass RMR evidence validation.'),
    ('accepted','Adaptive Research completed.'),
    ('failed','Adaptive Research failed. No unsupported evidence was accepted.'),
])
def test_durable_outcome_and_detail_without_actions(app,role,kind,message):
    accepted=int(kind=='accepted');rejected=int(kind=='findings_rejected')
    status='completed' if accepted else 'failed' if kind=='failed' else 'no_evidence'
    summary={'outcome':kind,'returned':accepted+rejected,'accepted':accepted,'rejected':rejected,
             'tasks_planned':4,'tasks_researched':4,'tasks_found':int(bool(accepted+rejected)),
             'tasks_not_found':4-int(bool(accepted+rejected)),
             'tasks':[], 'reasons':{'entity_mismatch':1} if rejected else {}}
    app.opportunities=[{**LIVE,'score':72+3*accepted,'adaptive_score_delta':3*accepted,
                        'research':{'eligible':False,'latest':{'status':status,'summary':summary}}}]
    app.start(role)
    expect(app.page.locator('[data-research-outcome]')).to_have_text(message)
    app.page.evaluate('sessionStorage.clear()')
    app.page.reload(wait_until='domcontentloaded')
    expect(app.page.locator('[data-research-outcome]')).to_have_text(message)
    app.page.locator('[data-open-piq]' if role=='CLIENT_ADMIN' else '[data-piq-profile]').click()
    detail=app.page.locator('.modal')
    expect(detail).to_contain_text(message)
    expect(detail).to_contain_text('Base Match: 72')
    expect(detail).to_contain_text(f'Research Adjustment: +{accepted*3}')
    expect(detail).to_contain_text(f'Final Match: {72+accepted*3}')
    if kind!='failed':
        expect(detail).to_contain_text('Tasks researched: 4 / 4 planned')
        expect(detail).to_contain_text(f'Accepted findings: {accepted}')
        expect(detail).to_contain_text(f'Rejected findings: {rejected}')
        if rejected:expect(detail).to_contain_text('entity mismatch: 1')
    assert app.post_calls==app.move_calls==0
    assert all(method=='GET' for method,_,_ in app.calls)


@pytest.mark.parametrize('role',['CLIENT_ADMIN','SALES_REP'])
@pytest.mark.parametrize('strong',[False,True])
def test_qualification_wording_keeps_score_information(app,role,strong):
    app.opportunities=[{**LIVE,'company_name':'Test Prospect','score':72 if strong else 35,
                        'confidence_score':81 if strong else 18,'evidence_completeness_pct':67 if strong else 0,
                        'status':'Qualified'}]
    app.start(role)
    expected='Discovered prospect — review profile evidence' if strong else 'Discovered prospect — fit unverified'
    expect(app.page.locator('#page')).to_contain_text(expected)
    expect(app.page.locator('#page')).not_to_contain_text('Qualified')
    expect(app.page.locator('#piq-quantity-help')).to_contain_text('new discovered prospects')
    app.page.locator('[data-open-piq]' if role=='CLIENT_ADMIN' else '[data-piq-profile]').click()
    expect(app.page.locator('.modal')).to_contain_text(expected)
    expect(app.page.locator('.modal')).to_contain_text('Confidence: '+('81%' if strong else '18%'))
    assert app.post_calls==0
