#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser(description='RMR Global v5.2.1 Client Administrator browser Golden Paths')
    parser.add_argument('--base-url', default='http://127.0.0.1:18081')
    parser.add_argument('--output-dir', default='qa/screenshots-v521-client-admin')
    parser.add_argument('--result', default='qa/V521-CLIENT-ADMIN-BROWSER-GOLDEN-PATHS.json')
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
        checks.append({'name': name, 'passed': bool(condition), 'detail': detail})
        print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f' | {detail}' if detail else ''), flush=True)
        if not condition:
            raise AssertionError(f'{name}: {detail}')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=args.chromium, args=['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--no-proxy-server','--proxy-bypass-list=*','--host-resolver-rules=MAP rmr-global.test 127.0.0.1'])
        page = browser.new_page(viewport={'width': 1600, 'height': 1100})
        page.set_default_timeout(15000)
        page.on('pageerror', lambda exc: errors.append(f'pageerror: {exc}'))
        page.on('console', lambda msg: errors.append(f'console.{msg.type}: {msg.text}') if msg.type == 'error' and '401' not in msg.text and 'favicon' not in msg.text.lower() else None)
        try:
            page.goto(base, wait_until='domcontentloaded')
            demo = '[data-demo-email="admin@kerry-real-estate.demo"]'
            page.wait_for_selector(demo)
            page.click(demo)
            page.wait_for_selector('.app-shell')
            check('Kerry Client Administrator reaches the normal customer workspace', 'Kerry' in page.locator('body').inner_text())

            page.goto(f'{base}/#/website', wait_until='domcontentloaded'); page.wait_for_selector('#ca-website-strategy')
            website_text = page.locator('#page').inner_text()
            check('Website workspace exposes External/Custom and RMR Managed strategies', 'External / Custom Website' in website_text and 'RMR Managed Website' in website_text, website_text[:600])
            check('Website strategy provides Save, Test, and Open actions', all(page.locator(sel).count() for sel in ['#ca-website-form','#ca-test-website','#ca-open-website']))
            page.screenshot(path=str(out/'01-website-strategy.png'), full_page=True)

            page.goto(f'{base}/#/campaigns', wait_until='domcontentloaded'); page.wait_for_selector('#ca-generate-social')
            page.click('#ca-generate-social'); page.wait_for_selector('#ca-social-form')
            page.fill('#ca-social-form textarea[name=objective]', f'{stamp} help Arizona homeowners plan a move to Northern Colorado')
            page.fill('#ca-social-form input[name=audience]', 'Arizona homeowners considering a move')
            page.fill('#ca-social-form input[name=tone]', 'friendly, professional and locally knowledgeable')
            page.fill('#ca-social-form input[name=call_to_action]', 'Schedule a relocation consultation')
            page.fill('#ca-social-form input[name=keywords]', 'relocation, Northern Colorado, home buyer')
            page.fill('#ca-social-form textarea[name=suggested_visual]', 'A family arriving at a Northern Colorado home')
            page.click('#ca-run-social'); page.wait_for_selector('.ca-social-card')
            page.wait_for_timeout(500)
            cards = page.locator('.ca-social-card')
            check('AI-assisted workflow generates four platform-specific social posts', cards.count() >= 4, f'cards={cards.count()}')
            social_text = page.locator('#page').inner_text()
            check('Social output includes hashtags, CTA, keywords, visual guidance and copy controls', all(x in social_text for x in ['Hashtags','CTA:','Keywords:','Suggested visual:','Copy Post','Copy Hashtags']), social_text[:1200])
            page.screenshot(path=str(out/'02-ai-social.png'), full_page=True)

            page.click('#ca-create-export'); page.wait_for_selector('#ca-export-form')
            page.fill('#ca-export-form input[name=name]', f'{stamp} Mailchimp Export')
            page.select_option('#ca-export-form select[name=provider_format]', 'mailchimp')
            page.fill('#ca-export-form input[name=lead_statuses]', '')
            page.fill('#ca-export-form input[name=sources]', '')
            page.fill('#ca-export-form input[name=subject]', 'Relocation planning follow-up')
            page.fill('#ca-export-form textarea[name=email_body]', 'Finished campaign content for external delivery.')
            page.click('#ca-save-export'); page.wait_for_selector('[data-ca-campaign-tab="exports"].active')
            page.wait_for_timeout(400)
            export_text = page.locator('#page').inner_text()
            check('Campaign creation produces a provider-ready export rather than bulk delivery', f'{stamp} Mailchimp Export' in export_text and 'Export CSV' in export_text and 'dedicated platform handles bulk delivery' in export_text, export_text[:1200])
            page.screenshot(path=str(out/'03-campaign-export.png'), full_page=True)

            page.goto(f'{base}/#/email', wait_until='domcontentloaded'); page.wait_for_selector('#ca-new-email')
            email_text = page.locator('#page').inner_text()
            check('Email workspace clearly defines client-owned one-to-one sending and no mass delivery', 'Client-owned sending' in email_text and 'does not operate a mass-email delivery system' in email_text, email_text[:900])
            page.locator('[data-email-tab="connections"]').first.click(); page.wait_for_selector('[data-connection-action="test"]')
            page.locator('[data-connection-action="test"]').first.click(); page.wait_for_timeout(400)
            page.click('#ca-new-email'); page.wait_for_selector('#ca-email-form')
            subject = f'{stamp} One-to-One Follow-Up'
            page.fill('#ca-email-form input[name=recipient_email]', f'{stamp.lower()}@example.com')
            page.fill('#ca-email-form input[name=recipient_name]', 'Golden Path Prospect')
            page.fill('#ca-email-form input[name=subject]', subject)
            page.fill('#ca-email-form textarea[name=body]', 'This individual message is sent from the connected client mailbox and retained as CRM activity.')
            page.click('#ca-send-email'); page.wait_for_timeout(500)
            page.locator('[data-email-tab="messages"]').first.click(); page.wait_for_timeout(350)
            check('One-to-one email is recorded in the actionable Messages view', subject in page.locator('#page').inner_text())
            page.screenshot(path=str(out/'04-email-activities.png'), full_page=True)

            page.goto(f'{base}/#/forecast', wait_until='domcontentloaded'); page.wait_for_selector('#ca-upload-forecast')
            forecast_text = page.locator('#page').inner_text()
            check('Forecasting displays currency and explicit number provenance', '$' in forecast_text and 'Imported actual sales' in forecast_text and 'CRM opportunities' in forecast_text, forecast_text[:1000])
            page.click('#ca-upload-forecast'); page.wait_for_selector('#ca-forecast-upload')
            csv_path = out / f'{stamp}-forecast.csv'
            csv_path.write_text('Account,Month,Amount,Target\nApex Distribution Center,January,$32,083.20,prior_actual\n', encoding='utf-8')
            # Use a comma-free currency value for CSV correctness while still proving file upload.
            csv_path.write_text('Account,Month,Amount,Target\nApex Distribution Center,January,32083.20,prior_actual\n', encoding='utf-8')
            page.set_input_files('#ca-forecast-upload input[name=file]', str(csv_path))
            page.click('#ca-preview-import'); page.wait_for_selector('#ca-import-preview .ca-confirm')
            check('Forecast CSV upload previews and validates rows before import', 'valid row' in page.locator('#ca-import-preview').inner_text().lower())
            page.click('#ca-commit-import'); page.wait_for_timeout(500)
            check('Forecast import completes through the normal client UI', 'Sales Forecasting' in page.locator('#page').inner_text())
            page.screenshot(path=str(out/'05-forecast-import.png'), full_page=True)

            page.goto(f'{base}/#/reports', wait_until='domcontentloaded'); page.wait_for_selector('[data-report-route]')
            report_text = page.locator('#page').inner_text()
            check('Reporting includes What Needs My Attention and actionable KPI drill-downs', 'What Needs My Attention?' in report_text and page.locator('[data-report-route]').count() >= 8, f'actions={page.locator("[data-report-route]").count()}')
            page.locator('[data-report-route]').first.click(); page.wait_for_timeout(350)
            check('Reporting action navigates to the underlying client workflow', 'Growth & Management Reporting' not in page.locator('#page').inner_text())
            page.screenshot(path=str(out/'06-reporting-action.png'), full_page=True)

            page.goto(f'{base}/#/training', wait_until='domcontentloaded'); page.wait_for_selector('#ca-add-training')
            page.click('#ca-add-training'); page.wait_for_selector('#ca-training-form')
            title = f'{stamp} Client Sales Workflow'
            page.fill('#ca-training-form input[name=title]', title)
            page.fill('#ca-training-form textarea[name=description]', 'How this client expects its sales team to use RMR Global.')
            page.fill('#ca-training-form input[name=media_url]', 'https://example.com/client-sales-training')
            page.select_option('#ca-training-form select[name=required]', 'true')
            page.locator('#ca-training-form input[name=user_id]').first.check()
            page.click('#ca-save-training'); page.wait_for_timeout(500)
            check('Client Administrator can add and assign company-specific workflow training', title in page.locator('#page').inner_text())
            page.screenshot(path=str(out/'07-client-training.png'), full_page=True)

            page.goto(f'{base}/#/organization', wait_until='domcontentloaded'); page.wait_for_selector('[data-team-reset]')
            org_text = page.locator('#page').inner_text()
            check('Team rows provide explicit Edit, Send Password Reset and Activate/Deactivate actions', all(x in org_text for x in ['Edit','Send Password Reset','Deactivate']))
            page.locator('[data-team-reset]').nth(1).click(); page.wait_for_selector('.modal')
            reset_text = page.locator('.modal').inner_text()
            check('Password reset workflow uses system email or an explicit Product Owner fallback', 'Authorized fallback only' in reset_text or 'Password reset sent' in page.locator('body').inner_text(), reset_text[:600])
            if page.locator('[data-close-modal]').count(): page.locator('[data-close-modal]').last.click()
            page.screenshot(path=str(out/'08-team-actions.png'), full_page=True)

            page.goto(f'{base}/#/solutions', wait_until='domcontentloaded'); page.wait_for_selector('[data-request-solution]')
            solutions_text = page.locator('#page').inner_text()
            check('Solutions Center distinguishes active services, available solutions, pricing, and no automatic charges', all(x in solutions_text for x in ['Active Services','Available Solutions','do not activate services or create charges']))
            page.locator('[data-request-solution]').first.click(); page.wait_for_selector('#ca-solution-form')
            page.fill('#ca-solution-form textarea[name=note]', f'{stamp} request a conversation about this service')
            page.select_option('#ca-solution-form select[name=preferred_contact_method]', 'Video Meeting')
            target_date = (datetime.now(timezone.utc).date() + timedelta(days=5)).isoformat()
            page.fill('#ca-solution-form input[name=contact_date]', target_date)
            page.fill('#ca-solution-form input[name=contact_time]', '11:00')
            page.fill('#ca-solution-form input[name=timezone]', 'America/Phoenix')
            page.click('#ca-submit-solution'); page.wait_for_timeout(500)
            check('Service request retains date, time, timezone and Request Submitted state without activation', 'Request Submitted' in page.locator('#page').inner_text() and 'America/Phoenix' in page.locator('#page').inner_text())
            page.screenshot(path=str(out/'09-solutions-request.png'), full_page=True)

            check('No browser page or console errors occurred', not errors, '; '.join(errors[:10]))
        except Exception as exc:
            status = 'failed'; failure = f'{type(exc).__name__}: {exc}'
            traceback.print_exc()
            try: page.screenshot(path=str(out/'FAILURE.png'), full_page=True)
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
