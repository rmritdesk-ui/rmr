#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser(description='RMR Global v5.3 Client Administrator browser Golden Paths')
    parser.add_argument('--base-url', default='http://127.0.0.1:18155')
    parser.add_argument('--output-dir', default='qa/screenshots-v53-client-admin')
    parser.add_argument('--result', default='qa/V53-CLIENT-ADMIN-BROWSER-GOLDEN-PATHS.json')
    parser.add_argument('--chromium', default='/usr/bin/chromium')
    args = parser.parse_args()

    base = args.base_url.rstrip('/')
    out = Path(args.output_dir).resolve(); out.mkdir(parents=True, exist_ok=True)
    result_path = Path(args.result).resolve(); result_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    checks: list[dict] = []
    errors: list[str] = []
    status = 'passed'; failure = ''
    started = datetime.now(timezone.utc)

    def check(name: str, condition: bool, detail: str = '') -> None:
        row = {'name': name, 'passed': bool(condition), 'detail': detail}
        checks.append(row)
        print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f' | {detail}' if detail else ''), flush=True)
        if not condition:
            raise AssertionError(f'{name}: {detail}')

    def shot(page, name: str) -> None:
        page.screenshot(path=str(out / name), full_page=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path=args.chromium,
            args=['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--no-proxy-server','--proxy-bypass-list=*','--host-resolver-rules=MAP rmr-global.test 127.0.0.1'],
        )
        context = browser.new_context(viewport={'width': 1680, 'height': 1150}, accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(20000)

        def on_console(msg):
            text = msg.text or ''
            if msg.type != 'error':
                return
            low = text.lower()
            # The login shell intentionally probes /api/auth/me before authentication.
            if '401' in low or 'favicon' in low:
                return
            errors.append(f'console.{msg.type}: {text}')

        page.on('console', on_console)
        page.on('pageerror', lambda exc: errors.append(f'pageerror: {exc}'))

        try:
            page.goto(base, wait_until='domcontentloaded')
            demo = '[data-demo-email="admin@kerry-real-estate.demo"]'
            page.wait_for_selector(demo)
            page.click(demo)
            page.wait_for_selector('.app-shell')
            page.wait_for_selector('.v53-hero')
            home_text = page.locator('#page').inner_text()
            check('Kerry Client Administrator reaches the v5.3 customer command center', 'CLIENT BUSINESS COMMAND CENTER' in home_text and 'Kerry Laughlin Real Estate' in page.locator('body').inner_text(), home_text[:500])
            check('Dashboard presents actionable KPIs and attention items', page.locator('.v53-metric').count() >= 4 and page.locator('.v53-attention').count() >= 1, f"metrics={page.locator('.v53-metric').count()} attention={page.locator('.v53-attention').count()}")
            shot(page, '01-client-dashboard.png')

            page.locator('.v53-metric').filter(has_text='Active Leads').first.click()
            page.wait_for_selector('.v53-crm-shell')
            check('Dashboard KPI drills into the corresponding CRM records', 'CONNECTED CRM' in page.locator('#page').inner_text() and page.locator('.v53-tab.active').inner_text().startswith('Leads'))

            # Create a lead through the browser.
            page.click('#v53-crm-new')
            page.wait_for_selector('[data-create-kind="lead"]')
            page.click('[data-create-kind="lead"]')
            page.wait_for_selector('#v53-new-form')
            lead_name = f'Golden Path {stamp}'
            lead_email = f'golden-{stamp.lower()}@example.com'
            page.fill('#v53-new-form [name="contact_name"]', lead_name)
            page.fill('#v53-new-form [name="company_name"]', f'{lead_name} Company')
            page.fill('#v53-new-form [name="email"]', lead_email)
            page.fill('#v53-new-form [name="phone"]', '602-555-0199')
            page.select_option('#v53-new-form [name="source"]', 'Website')
            page.fill('#v53-new-form [name="notes"]', 'v5.3 browser Golden Path lead')
            page.click('#v53-save-new')
            page.wait_for_timeout(700)
            page.goto(f'{base}/#/crm?tab=leads&search={lead_name}', wait_until='domcontentloaded')
            page.wait_for_selector('.v53-crm-shell')
            lead_row = page.locator('.v53-lead-row').filter(has_text=lead_name).first
            check('CRM creates an actionable lead record', lead_row.count() == 1 and lead_row.locator('[data-open-record="lead"]').count() >= 1)

            # Controlled conversion: user confirms business details before records are created.
            lead_row.locator('[data-convert-lead]').click()
            page.wait_for_selector('#v53-convert-form')
            opp_name = f'{lead_name} Relocation Opportunity'
            page.fill('#v53-convert-form [name="opportunity_name"]', opp_name)
            page.select_option('#v53-convert-form [name="stage"]', 'Qualified')
            page.fill('#v53-convert-form [name="value"]', '485000')
            page.fill('#v53-convert-form [name="probability"]', '65')
            page.fill('#v53-convert-form [name="expected_close_date"]', (datetime.now(timezone.utc)+timedelta(days=75)).date().isoformat())
            page.fill('#v53-convert-form [name="next_action"]', 'Schedule buyer consultation')
            check('Lead conversion requires confirmation of stage, value, probability, close date and next action', all(page.locator(f'#v53-convert-form [name="{name}"]').count() for name in ['stage','value','probability','expected_close_date','next_action']))
            page.click('#v53-confirm-convert')
            page.wait_for_timeout(900)
            page.goto(f'{base}/#/crm?tab=opportunities&search={lead_name}', wait_until='domcontentloaded')
            page.wait_for_selector('.v53-crm-shell')
            opp_card = page.locator('.v53-opportunity-card').filter(has_text=opp_name).first
            check('Controlled conversion creates a useful opportunity with confirmed value and next action', opp_card.count() == 1 and '$485,000' in opp_card.inner_text() and 'Schedule buyer consultation' in opp_card.inner_text(), opp_card.inner_text() if opp_card.count() else '')
            check('Opportunity card itself is actionable and exposes contextual email', opp_card.get_attribute('data-open-record') == 'opportunity' and opp_card.locator('[data-email-opportunity]').count() == 1)
            shot(page, '02-modern-crm-pipeline.png')

            opp_card.click()
            page.wait_for_selector('.modal')
            detail_text = page.locator('.modal').inner_text()
            check('Opportunity opens a connected 360-degree relationship view', all(x in detail_text for x in ['Record Details','Related Records','Activity Timeline','Communication','Edit Opportunity']), detail_text[:1200])
            page.locator('.modal [data-record-action="email"]').click()
            page.wait_for_selector('#v53-email-form')
            check('Contextual email prepopulates the converted CRM contact', page.input_value('#v53-email-form [name="recipient_email"]') == lead_email and lead_name in page.input_value('#v53-email-form [name="recipient_name"]'))
            subject = f'{stamp} Buyer consultation follow-up'
            page.fill('#v53-email-form [name="subject"]', subject)
            page.fill('#v53-email-form [name="body"]', 'Thank you for reaching out. This one-to-one message is sent through the client mailbox and retained against the opportunity.')
            page.click('#v53-send-email')
            page.wait_for_timeout(850)
            page.wait_for_selector('.v53-message-list')
            msg = page.locator('.v53-message-list button').filter(has_text=subject).first
            check('One-to-one email is sent through the client mailbox and appears in Messages', msg.count() == 1)
            msg.click(); page.wait_for_selector('.modal')
            msg_text = page.locator('.modal').inner_text()
            check('Sent-message drill-down shows delivery, actor, complete message and CRM relationship', all(x.lower() in msg_text.lower() for x in ['Delivery','CRM Relationship','Sent by','Message',opp_name]), msg_text[:1200])
            shot(page, '03-message-and-crm-context.png')
            page.locator('.modal [data-close-modal]').last.click()

            # ProspectIQ context and continuity into CRM.
            page.goto(f'{base}/#/piq', wait_until='domcontentloaded'); page.wait_for_selector('.v53-prospect-card')
            piq_text = page.locator('#page').inner_text()
            check('ProspectIQ clearly labels the local provider mode and preserves target/discovery workflow', 'Demonstration provider active' in piq_text and 'Target Profile' in piq_text and 'Run Discovery' in piq_text)
            candidate = page.locator('.v53-prospect-card').filter(has=page.locator('[data-research-piq]')).first
            if not candidate.count():
                candidate = page.locator('.v53-prospect-card').filter(has=page.locator('[data-move-piq]')).first
            if candidate.count():
                company = candidate.locator('h3').inner_text()
                if candidate.locator('[data-research-piq]').count():
                    candidate.locator('[data-research-piq]').click(); page.wait_for_timeout(850)
                    candidate = page.locator('.v53-prospect-card').filter(has_text=company).first
                candidate.locator('[data-open-piq]').click(); page.wait_for_selector('.modal')
                piq_detail = page.locator('.modal').inner_text()
                check('Prospect profile exposes score, evidence, potential and research status', all(x.lower() in piq_detail.lower() for x in ['match score','Evidence','Potential','Research','CRM']), piq_detail[:800])
                check('Adaptive Research exposes actual evidence details when completed', 'No evidence yet' not in piq_detail and page.locator('.modal .v53-evidence-list div').count() >= 1, piq_detail[:1000])
                if page.locator('#v53-detail-move-crm').count():
                    page.click('#v53-detail-move-crm'); page.wait_for_timeout(900)
                check('ProspectIQ moves intelligence into the CRM workflow', 'CONNECTED CRM' in page.locator('#page').inner_text() and company in page.locator('#page').inner_text(), company)
            shot(page, '04-prospectiq-continuity.png')

            # Campaign content generation and campaign package clarity.
            page.goto(f'{base}/#/campaigns', wait_until='domcontentloaded'); page.wait_for_selector('#v53-generate-social')
            page.click('#v53-generate-social'); page.wait_for_selector('#v53-social-generate')
            page.fill('#v53-social-generate [name="objective"]', f'{stamp} promote relocation consultations for Arizona homeowners moving to Northern Colorado')
            page.fill('#v53-social-generate [name="audience"]', 'Arizona homeowners planning a Colorado move')
            page.fill('#v53-social-generate [name="tone"]', 'Confident, local and genuinely helpful')
            page.fill('#v53-social-generate [name="cta"]', 'Schedule a relocation planning call')
            page.fill('#v53-social-generate [name="keywords"]', 'Arizona, Colorado, relocation, home buying')
            page.fill('#v53-social-generate [name="visual"]', 'Warm photo of a family planning a cross-state move')
            page.click('#v53-run-social'); page.wait_for_timeout(1000)
            page.wait_for_selector('.v53-platform-preview')
            cards = page.locator('.v53-platform-preview')
            platforms = [cards.nth(i).locator('header strong').inner_text().lower() for i in range(cards.count())]
            posts = [cards.nth(i).locator('.v53-social-post p').inner_text() for i in range(cards.count())]
            check('Social Studio produces four visibly differentiated platform previews', len(set(platforms)) >= 4 and len(set(posts)) >= 4, f'platforms={platforms}')
            social_text = page.locator('#page').inner_text()
            check('Copy destinations and next actions are explicit', all(x in social_text for x in ['Copy Complete Post','Copy Post to Clipboard','Copy Hashtags to Clipboard','Open / Edit','Regenerate']))
            shot(page, '05-campaigns-social-studio.png')

            page.click('#v53-create-export'); page.wait_for_selector('#v53-export-form')
            package_name = f'{stamp} Mailchimp Campaign Package'
            page.fill('#v53-export-form [name="name"]', package_name)
            page.select_option('#v53-export-form [name="provider"]', 'mailchimp')
            page.fill('#v53-export-form [name="subject"]', 'Relocation planning ideas for your next move')
            page.fill('#v53-export-form [name="preview"]', 'Helpful next steps from Kerry Laughlin Real Estate')
            page.fill('#v53-export-form [name="body"]', 'This approved campaign content is prepared in RMR Global and delivered through the client’s dedicated bulk-email platform.')
            page.fill('#v53-export-form [name="cta"]', 'Schedule a consultation')
            page.click('#v53-create-package'); page.wait_for_timeout(900)
            page.wait_for_selector('.v53-package-card')
            package_card = page.locator('.v53-package-card').filter(has_text=package_name).first
            check('Email campaign creates a provider-ready package without bulk delivery', package_card.count() == 1 and 'Review Package & Instructions' in package_card.inner_text())
            package_card.locator('[data-open-export]').click(); page.wait_for_selector('.modal')
            package_text = page.locator('.modal').inner_text()
            check('Campaign package explains destination, recipients, content and next steps', all(x in package_text for x in ['Campaign Content','What happens next?','Approved Email Content','Download Recipient CSV','Mailchimp']), package_text[:1400])
            page.locator('.modal [data-close-modal]').last.click()

            # Tenant forecast source transparency and visual dashboard.
            page.goto(f'{base}/#/forecast', wait_until='domcontentloaded'); page.wait_for_selector('.v53-chart')
            forecast_text = page.locator('#page').inner_text()
            check('Forecast is explicitly scoped to Kerry and identifies each source', 'kerry laughlin real estate sales forecast' in forecast_text.lower() and all(x.lower() in forecast_text.lower() for x in ['Operating Forecast','Closed Won Revenue','Weighted Pipeline','Imported Actuals']), forecast_text[:1000])
            check('Forecast includes a visual trend and separate CRM and ProspectIQ scrollable grids', page.locator('.v53-chart-month').count() == 12 and page.locator('.v53-forecast-table').count() == 2 and 'CRM Opportunity & Relationship Forecast' in forecast_text and 'ProspectIQ Pipeline Potential' in forecast_text)
            page.click('#v53-upload-forecast'); page.wait_for_selector('#v53-forecast-upload')
            check('Forecast primary import workflow accepts CSV and Excel files with preview', '.csv,.xlsx' in (page.get_attribute('#v53-forecast-upload input[type=file]','accept') or '') and page.locator('#v53-preview-forecast').count() == 1)
            page.locator('.modal [data-close-modal]').last.click()
            shot(page, '06-tenant-forecast.png')

            # Actionable reporting.
            page.goto(f'{base}/#/reports', wait_until='domcontentloaded'); page.wait_for_selector('.v53-attention-panel')
            report_text = page.locator('#page').inner_text()
            check('Reporting provides attention guidance, clickable KPIs, funnel and source attribution', 'What needs my attention?' in report_text and page.locator('.v53-metric').count() >= 6 and page.locator('.v53-funnel button').count() >= 1 and page.locator('.v53-source-list button').count() >= 1)
            shot(page, '07-actionable-reporting.png')

            # Client-managed training file and retrieval.
            page.goto(f'{base}/#/training', wait_until='domcontentloaded'); page.wait_for_selector('#v53-add-training')
            page.click('#v53-add-training'); page.wait_for_selector('#v53-training-form')
            training_title = f'{stamp} Sales Workflow Guide'
            pdf = out / f'{stamp}-training.pdf'
            pdf.write_bytes(b'%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n')
            page.fill('#v53-training-form [name="title"]', training_title)
            page.fill('#v53-training-form [name="category"]', 'Sales Workflow')
            page.select_option('#v53-training-form [name="media_type"]', 'uploaded_file')
            page.fill('#v53-training-form [name="description"]', 'How our team should use RMR Global during the sales process.')
            page.set_input_files('#v53-training-form [name="file"]', str(pdf))
            page.check('#v53-training-form [name="required"]')
            page.click('#v53-save-training'); page.wait_for_timeout(900)
            page.wait_for_selector('.v53-training-card')
            training_card = page.locator('.v53-training-card').filter(has_text=training_title).first
            check('Client Admin can add, assign and mark uploaded training required', training_card.count() == 1 and 'Required' in training_card.inner_text() and 'Open / Download' in training_card.inner_text())
            href = training_card.locator('a').get_attribute('href')
            resp = page.request.get(f'{base}{href}')
            check('Uploaded training content can be opened or downloaded', resp.ok, f'status={resp.status}')
            shot(page, '08-client-training-library.png')

            # Team experience.
            page.goto(f'{base}/#/organization', wait_until='domcontentloaded'); page.wait_for_selector('.v53-people-grid')
            check('Team workspace offers People, Org View and List View', all(page.locator(f'[data-org-view="{v}"]').count() for v in ['cards','org','list']))
            page.click('[data-org-view="org"]'); page.wait_for_selector('.v53-org-chart')
            page.click('[data-org-view="list"]'); page.wait_for_selector('.v53-table')
            check('Team records remain tenant-scoped and editable', page.locator('[data-edit-person]').count() >= 1 and 'Kerry' in page.locator('#page').inner_text())
            shot(page, '09-team-organization.png')

            # Solutions policy and request capture.
            page.goto(f'{base}/#/solutions', wait_until='domcontentloaded'); page.wait_for_selector('.v53-policy-banner')
            solutions_text = page.locator('#page').inner_text()
            check('Solutions clearly separates active services from requests and forbids automatic activation/billing', all(x in solutions_text for x in ['Your RMR Solutions','Explore Additional Solutions','No automatic activation or billing']))
            check('Solutions does not expose unexplained placeholder $0 pricing', '$0.00' not in solutions_text and '$0/month' not in solutions_text, solutions_text[:1000])
            request_btn = page.locator('[data-request-solution]').first
            if request_btn.count():
                request_btn.click(); page.wait_for_selector('#v53-solution-form')
                modal_text = page.locator('.modal').inner_text()
                check('Solution request captures business need, date, time and timezone and is not an appointment', all(x in modal_text for x in ['not a confirmed appointment','Preferred date','Preferred time','Time zone']))
                page.locator('.modal [data-close-modal]').last.click()
            shot(page, '10-solutions-center.png')

            # Preserve existing website functionality under the new shell.
            page.goto(f'{base}/#/website', wait_until='domcontentloaded'); page.wait_for_selector('#ca-website-strategy', timeout=30000)
            website_text = page.locator('#page').inner_text()
            check('Existing Website functionality remains reachable and tenant-scoped', 'Website' in website_text and 'Kerry' in page.locator('body').inner_text(), website_text[:700])
            shot(page, '11-website-preserved.png')

            check('No unexpected browser console or page errors occurred', not errors, '; '.join(errors[:10]))
        except Exception as exc:
            status = 'failed'; failure = f'{type(exc).__name__}: {exc}'
            traceback.print_exc()
            try: shot(page, 'FAILURE.png')
            except Exception: pass
        finally:
            browser.close()

    result = {
        'status': status,
        'release': '5.3.1-final-production-corrections-po1',
        'base_url': base,
        'started_utc': started.isoformat(),
        'completed_utc': datetime.now(timezone.utc).isoformat(),
        'passed': sum(1 for row in checks if row['passed']),
        'failed': sum(1 for row in checks if not row['passed']) + (1 if status == 'failed' and all(row['passed'] for row in checks) else 0),
        'checks': checks,
        'browser_errors': errors,
        'failure': failure,
        'screenshots': sorted(p.name for p in out.glob('*.png')),
    }
    result_path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': status, 'passed': result['passed'], 'failed': result['failed']}, indent=2))
    return 0 if status == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
