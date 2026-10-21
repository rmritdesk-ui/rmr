"""Real Social Studio modules and endpoints, isolated browser and database."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from test_social_editorial import studio, brief

pw = pytest.importorskip('playwright.sync_api')
PUBLIC = Path(__file__).resolve().parents[1] / 'public'


@pytest.fixture
def page(studio):
    with pw.sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width':1200,'height':900})
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        def serve(route):
            r=route.request; url=urlsplit(r.url)
            assert url.hostname=='audit.test'
            if url.path.startswith('/api/'):
                result=studio.client.request(r.method,url.path,content=r.post_data,
                    headers={'Content-Type':'application/json','X-RMR-Request':'1'})
                route.fulfill(status=result.status_code,content_type='application/json',body=result.content)
            elif url.path.endswith(('.js','.css')):
                file=(PUBLIC/url.path.lstrip('/')).resolve()
                assert file.is_relative_to(PUBLIC)
                route.fulfill(content_type='application/javascript' if file.suffix=='.js' else 'text/css',
                              body=file.read_text(encoding='utf-8'))
            else:
                route.fulfill(content_type='text/html',body='''<meta charset="utf-8">
                <link rel="stylesheet" href="/styles.css"><link rel="stylesheet" href="/v53-experience.css">
                <main id="page"></main><div id="modal-root"></div><script type="module">
                import {state} from '/state.js';
                import {renderV53ClientExperience} from '/pages/v53_client_experience.js';
                state.user={tenant_role:'CLIENT_ADMIN',global_role:null};
                state.selectedTenantId='''+json.dumps(studio.a.id)+''';
                const ctx={navigate:async route=>{state.routeQuery=Object.fromEntries(new URLSearchParams(route.split('?')[1]||''));
                await renderV53ClientExperience('campaigns',document.querySelector('#page'),ctx);}};
                window.copied=[];
                Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>window.copied.push(text)}});
                await ctx.navigate('campaigns');</script>''')
        page.route('**/*',serve)
        page.goto('http://audit.test/')
        page.locator('#v53-generate-social').wait_for()
        yield page
        assert not errors,errors
        browser.close()


def test_generate_edit_history_regenerate_and_calendar(page,studio):
    assert page.get_by_text('Template-assisted content generation',exact=True).count()==1
    page.locator('#v53-generate-social').click()
    form=page.locator('#v53-social-generate')
    form.locator('[name=objective]').fill(brief().objective)
    form.locator('[name=audience]').fill(brief().audience)
    page.locator('#v53-run-social').click()
    pw.expect(page.get_by_text('Latest generated campaign',exact=True)).to_be_visible()
    card=page.locator('.v53-platform-preview').first
    before=card.locator('.v53-social-post p').inner_text()
    card.locator('[data-copy-complete]').click()
    tags=card.locator('.v53-hashtags').inner_text()
    assert page.evaluate('window.copied.at(-1)')==f'{before}\n\n{tags}'.strip()
    card.locator('[data-open-social]').click()
    page.locator('[name=post_text]').fill('My carefully edited post.')
    page.locator('#v53-save-social').click()
    pw.expect(page.locator('.v53-social-post').first).to_contain_text('My carefully edited post.')
    page.once('dialog',lambda d:d.dismiss())
    page.locator('[data-regenerate-social]').first.click()
    assert page.locator('.v53-social-post').first.inner_text().find('My carefully edited post.')>=0
    page.once('dialog',lambda d:d.accept())
    page.locator('[data-regenerate-social]').first.click()
    pw.expect(page.locator('.v53-social-post').first).not_to_contain_text('My carefully edited post.')
    page.locator('[data-open-social]').first.click()
    page.get_by_text('Previous versions (2)',exact=True).click()
    pw.expect(page.get_by_text('My carefully edited post.',exact=True)).to_be_visible()
    page.locator('[data-close-modal]').first.click()
    page.locator('[data-campaign-tab=calendar]').click()
    pw.expect(page.locator('.v53-calendar-item')).to_have_count(4)


def test_previous_campaigns_and_x_feedback(page,studio):
    base=f'/api/v521/tenants/{studio.a.id}/social/generate'
    studio.client.post(base,json=brief(0).model_dump())
    studio.client.post(base,json=brief(1).model_dump())
    page.reload()
    pw.expect(page.get_by_text('Previous drafts (4)',exact=True)).to_be_visible()
    assert page.locator('.v53-platform-preview:visible').count()==4
    page.get_by_text('Previous drafts (4)',exact=True).click()
    assert page.locator('.v53-platform-preview:visible').count()==8
    page.locator('article.X [data-open-social]').first.click()
    pw.expect(page.locator('#social-length-feedback')).to_contain_text('/280')
    page.locator('[name=post_text]').fill('漢'*200)
    page.locator('[name=hashtags]').fill('')
    pw.expect(page.locator('#social-length-feedback')).to_contain_text('400')
    counts=page.evaluate("""async()=>{const {xWeight}=await import('/pages/social_editorial.js');return [xWeight('漢😀'),xWeight('https://example.test/'+'a'.repeat(1000)),xWeight('e\\u0301')]}""")
    assert counts==[4,23,1]
