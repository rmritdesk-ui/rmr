"""Offline editorial and real HTTP/storage regressions; never contact providers."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from rmr_platform import client_admin_corrections as generation, cumulative_product_repair as editing
from rmr_platform.db import Base, get_db
from rmr_platform.models import Tenant, User, AuditEvent
from rmr_platform.cb1_models import CB1SocialContent
from rmr_platform.client_admin_models import SocialGenerationMetadata, CampaignExportPackage
from rmr_platform.cumulative_product_models import SocialContentRevision
from rmr_platform.security import current_user
from rmr_platform.social_editorial import generate, complete_post, x_weight

CASES = [
    ('Promote home buying consultations in Virginia', 'first-time home buyers', ['Virginia', 'HomeBuying']),
    ('Introduce plumbing repair services', 'local homeowners', ['Plumbing', 'Repairs']),
    ('Explain software development project planning', 'small business owners', ['Software', 'Planning']),
    ('Invite volunteers to a nonprofit community gathering', 'community volunteers', ['Community', 'Volunteers']),
    ('Announce seasonal catering menus', 'event planners', ['Catering', 'Menus']),
]


def brief(case=0, **overrides):
    objective, audience, keywords = CASES[case]
    return generation.SocialGenerateIn(**dict(
        dict(objective=objective, audience=audience, keywords=keywords,
             tone='friendly and approachable', call_to_action='Contact us to discuss your plans.',
             suggested_visual='Use an approved photo supplied by the business.'), **overrides))


@pytest.mark.parametrize('case', range(5))
def test_business_content_and_variations(case):
    p = brief(case)
    versions = [generate(p, v) for v in range(3)]
    for version in versions:
        assert set(version) == {'facebook', 'instagram', 'linkedin', 'x'}
        for platform, item in version.items():
            assert p.objective not in item['post']
            assert p.suggested_visual not in item['post']
            assert item['suggested_visual'] == p.suggested_visual
            assert p.call_to_action in item['post']
            assert not any(word in item['post'].lower() for word in ['guarantee', 'award-winning', 'testimonials', '20 years'])
            if case != 0:
                assert not any(word in complete_post(item['post'], item['hashtags']) for word in ['RealEstate', 'Virginia', 'relocation'])
            assert len(set(item['hashtags'].lower().split())) == len(item['hashtags'].split())
        assert p.audience.lower() in version['facebook']['post'].lower()
        assert '✨' in version['instagram']['post']
        assert '✨' not in version['linkedin']['post']
        assert x_weight(complete_post(version['x']['post'], version['x']['hashtags'])) <= 280
        assert len(version['x']['post']) < len(version['linkedin']['post'])
    for platform in versions[0]:
        assert len({v[platform]['post'] for v in versions}) == 3
    formal = generate(brief(case, tone='formal professional'))
    assert '✨' not in formal['instagram']['post']
    assert 'begin with the information needed to make a decision' in formal['facebook']['post']
    assert formal['facebook']['post'] != versions[0]['facebook']['post']


@pytest.mark.parametrize('case', range(5))
def test_editorial_topic_specificity_and_no_robotic_labels(case):
    expected = ['listing', 'plumbing', 'software', 'involved', 'menu'][case]
    p = brief(case)
    first = generate(p)
    assert expected in first['facebook']['post'].split('\n')[0].lower()
    assert len({item['post'].split('\n')[0] for item in first.values()}) == 4
    for variant in range(3):
        outputs = generate(p, variant)
        assert len({item['post'].split('\n')[0] for item in outputs.values()}) == 4
        for platform, item in outputs.items():
            assert f'For {p.audience}:' not in item['post']
            assert 'What matters most to you?' not in item['post']
            assert 'Your questions. Your priorities.' not in item['post']
            assert 'Applied to' not in item['post']
            assert 'menus starts' not in item['post']
            assert 'services starts' not in item['post']
            assert 'consultations in Virginia starts' not in item['post']
            assert '•' not in item['post']
            assert item['post'].count(p.call_to_action) == 1
            assert not any(claim in item['post'].lower() for claim in ['our team', 'we offer', 'we guarantee', 'available now', 'free consultation'])
            assert item['editorial']['generator_version'] == 'editorial-2'


def test_unmatched_topic_and_tone_do_not_infer_business():
    p = brief(objective='Introduce bookbinding workshops', audience='adult learners', tone='formal, no emoji')
    result = generate(p)
    for item in result.values():
        assert not any(word in item['post'].lower() for word in ['home buying', 'plumbing', 'software', 'catering'])
        assert '✨' not in item['post']
    assert 'bookbinding workshops' in result['facebook']['post']


def test_complete_x_budget_and_uncertain_brief():
    assert x_weight('abc') == 3
    assert x_weight('https://example.test/' + 'a'*1000) == 23
    assert x_weight('漢😀') == 4
    assert x_weight('e\u0301') == 1
    assert x_weight('https://example.test/path.') == 24
    assert x_weight('https://'+'x'*300) > 280
    for cta in ['漢'*280, 'a'*299, 'Visit https://example.test/'+'x'*200]:
        item = generate(brief(call_to_action=cta, keywords=['x'*40]*20))['x']
        assert x_weight(complete_post(item['post'], item['hashtags'])) <= 280
        assert item['post'].endswith(('.', '?')) or 'https://' in item['post']
    item = generate(brief(objective='Write a post. Make sure it sounds exciting and include claims.'))['facebook']
    assert item['editorial']['review_note']
    assert 'include claims' not in item['post']


@pytest.fixture
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv('RMR_AI_PROVIDER', 'local')
    def no_network(*args, **kwargs):
        pytest.fail('Generation must not call an external provider')
    monkeypatch.setattr(generation.httpx, 'post', no_network)
    engine = create_engine(f"sqlite:///{tmp_path / 'social.db'}", connect_args={'check_same_thread': False})
    tables = set()
    def include(table):
        if table in tables:
            return
        tables.add(table)
        for fk in table.foreign_keys:
            include(fk.column.table)
    for model in (Tenant, User, AuditEvent, CB1SocialContent, SocialGenerationMetadata,
                  SocialContentRevision, CampaignExportPackage):
        include(model.__table__)
    Base.metadata.create_all(engine, tables=list(tables))
    with Session(engine, expire_on_commit=False) as db:
        a, b = Tenant(name='Business A', slug='social-a'), Tenant(name='Business B', slug='social-b')
        db.add_all([a,b]); db.commit()
        user = User(tenant_id=a.id, tenant_role='CLIENT_ADMIN', email='social@example.invalid',
                    full_name='Editor', password_hash='no-login')
        db.add(user); db.commit()
    app = FastAPI()
    app.include_router(generation.router); app.include_router(editing.router)
    def database():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[current_user] = lambda: user
    with TestClient(app, headers={'X-RMR-Request': '1'}) as client:
        yield SimpleNamespace(client=client, a=a, b=b, user=user)
    engine.dispose()


def test_generate_edit_regenerate_history_and_authorization(studio):
    c, tenant = studio.client, studio.a.id
    base = f'/api/v521/tenants/{tenant}/social'
    response = c.post(base+'/generate', json=brief().model_dump())
    assert response.status_code == 200, response.text
    rows = c.get(base).json()['items']
    assert len(rows) == 4
    assert len({r['generation']['metadata_json']['batch_id'] for r in rows}) == 1
    row = rows[0]; url = f'/api/v522/tenants/{tenant}/social/{row["id"]}'
    first = c.post(url+'/regenerate', json={})
    assert first.status_code == 200, first.text
    assert first.json()['item']['post_text'] != row['post_text']
    assert c.patch(url,json={'title':'My edit','post_text':'My approved wording.', 'hashtags':'#Safe'}).status_code == 200
    assert c.post(url+'/regenerate',json={}).status_code == 409
    assert c.get(url).json()['item']['post_text'] == 'My approved wording.'
    assert c.post(url+'/regenerate',json={'confirm_replace':True}).status_code == 200
    detail = c.get(url).json()
    assert len(detail['revisions']) == 3
    assert detail['revisions'][0]['snapshot_json']['post_text'] == 'My approved wording.'
    assert detail['item']['id'] == row['id']
    assert detail['generation']['provider'] == 'local'
    assert c.post(base+'/generate', json=brief(1).model_dump()).status_code == 200
    assert len(c.get(base).json()['items']) == 8
    studio.user.tenant_id = studio.b.id
    assert c.get(base).status_code == 403
    assert c.get(url).status_code == 403
    assert c.get(url.replace(tenant,studio.b.id)).status_code == 404
    assert c.post(url+'/regenerate',json={'confirm_replace':True}).status_code == 403
    assert c.patch(url,json={'post_text':'Forbidden'}).status_code == 403
    studio.user.tenant_id = tenant; studio.user.tenant_role = 'EXECUTIVE_VIEWER'
    assert c.post(base+'/generate',json=brief().model_dump()).status_code == 403
    assert c.patch(url,json={'post_text':'Forbidden'}).status_code == 403
    assert c.post(url+'/regenerate',json={'confirm_replace':True}).status_code == 403


def test_mode_does_not_depend_on_demo_install(studio):
    response = studio.client.get(f'/api/v521/tenants/{studio.a.id}/environment')
    assert response.json()['social_generation_mode'] == 'template'


def test_compound_instruction_generate_and_regenerate(studio):
    from rmr_platform.social_editorial import _brief
    objective = 'Promote our real estate services in Virginia and encourage first-time home buyers to contact us for help finding a home.'
    p = brief(objective=objective)
    assert _brief(p) == ('promotion', 'our real estate services in Virginia', False)
    assert _brief(brief(objective='Promote home buying and selling services'))[1] == 'home buying and selling services'
    assert _brief(brief(objective='Promote and encourage people to contact us'))[2] is True
    assert _brief(brief(objective='Promote our services while encouraging people to call'))[2] is True
    base = f'/api/v521/tenants/{studio.a.id}/social'
    response = studio.client.post(base+'/generate', json=p.model_dump())
    assert response.status_code == 200, response.text
    for row in response.json()['items']:
        assert 'virginia' in row['post_text'].lower()
        assert 'and encourage' not in row['post_text']
        url = f'/api/v522/tenants/{studio.a.id}/social/{row["id"]}'
        for variant in (1, 2):
            result = studio.client.post(url+'/regenerate', json={})
            assert result.status_code == 200, result.text
            data = result.json()
            assert 'and encourage' not in data['item']['post_text']
            assert data['generation']['objective'] == objective
            assert data['generation']['metadata_json']['variant'] == variant
        assert len(studio.client.get(url).json()['revisions']) == 2


def test_first_home_compound_brief_natural_copy_all_platforms(studio):
    # Six-input reproduction; keep the supplied CTA verbatim, not inferred.
    p = brief(
        objective='Promote our real estate services in Virginia and encourage first-time home buyers to contact us for help finding a home.',
        audience='first-time home buyers', tone='friendly and approachable',
        call_to_action='Contact us for help finding a home.',
        keywords=['Virginia', 'HomeBuying'],
        suggested_visual='Use an approved photo supplied by the business.')
    base = f'/api/v521/tenants/{studio.a.id}/social'
    response = studio.client.post(base+'/generate', json=p.model_dump())
    assert response.status_code == 200, response.text
    expected = "Buying your first home in Virginia? Tell us what you're looking for, and let's start the conversation. Contact us for help finding a home."
    assert next(r for r in response.json()['items'] if r['platform']=='X')['post_text'] == expected
    for row in response.json()['items']:
        url = f'/api/v522/tenants/{studio.a.id}/social/{row["id"]}'
        versions = [row['post_text']]
        for _ in range(2):
            result = studio.client.post(url+'/regenerate', json={})
            assert result.status_code == 200, result.text
            data = result.json()
            versions.append(data['item']['post_text'])
            meta = data['generation']
            assert meta['objective'] == p.objective
            assert meta['audience'] == p.audience
            assert meta['tone'] == p.tone
            assert meta['call_to_action'] == p.call_to_action
            assert meta['keywords_json'] == p.keywords
            assert meta['suggested_visual'] == p.suggested_visual
        assert len(set(versions)) == 3
        for text in versions:
            assert 'Virginia' in text and p.call_to_action in text
            assert 'Our real estate services' not in text
            assert 'ask for the details relevant to your situation' not in text
            assert 'and encourage' not in text
    fallback = generate(brief(objective='Promote our services while encouraging people to call',
                              call_to_action=p.call_to_action))['x']
    assert fallback['post'] == 'Have questions about your next steps? Tell us what you would like to know. '+p.call_to_action
    assert fallback['editorial']['review_note']
    assert generate(p.model_copy(update={'audience':'the intended audience'}))['x']['post'] == expected


@pytest.mark.parametrize('provider', ['local', 'mock', 'demonstration'])
def test_all_offline_paths_never_use_provider(studio, monkeypatch, provider):
    monkeypatch.setenv('RMR_AI_PROVIDER',provider)
    result=studio.client.post(f'/api/v521/tenants/{studio.a.id}/social/generate',json=brief().model_dump())
    assert result.status_code==200
    assert result.json()['provider']==provider


def test_legacy_record_requires_confirmation_and_keeps_history(studio):
    # Existing records without generation metadata remain accessible and safe.
    from rmr_platform.db import get_db
    dependency=studio.client.app.dependency_overrides[get_db]
    dbgen=dependency(); db=next(dbgen)
    try:
        row=CB1SocialContent(tenant_id=studio.a.id,platform='FACEBOOK',title='Legacy campaign',
                            post_text='Original saved content.',created_by=studio.user.id)
        db.add(row);db.commit();identity=row.id
    finally:
        dbgen.close()
    url=f'/api/v522/tenants/{studio.a.id}/social/{identity}'
    assert studio.client.post(url+'/regenerate',json={}).status_code==409
    assert studio.client.post(url+'/regenerate',json={'confirm_replace':True}).status_code==200
    assert studio.client.get(url).json()['revisions'][0]['snapshot_json']['post_text']=='Original saved content.'
