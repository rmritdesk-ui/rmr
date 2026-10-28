"""Isolated Chromium checks of the actual New Client form; no backend writes."""
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright


class ClientWebsiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)
        source = (Path(__file__).resolve().parents[1] / 'public/pages/admin.js').read_text(encoding='utf-8')
        cls.script = source[source.index('async function addClientModal('):source.index('\nfunction showClientCreated(')]
        cls.script += '\n' + '\n'.join(line for line in source.splitlines() if line.startswith(('function field(', 'function selectField(')))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.page.route('**/*', lambda r: r.fulfill(status=200, content_type='text/html', body='<html><body></body></html>'))
        self.page.goto('http://fixture.test')
        self.page.evaluate('''() => {
          window.posts=[]; window.created=false;
          window.$=(s,r=document)=>r.querySelector(s);
          window.esc=s=>String(s).replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;');
          window.money=String; window.state={}; window.toast=()=>{};
          window.applyFieldErrors=()=>{}; window.showClientCreated=()=>{created=true};
          window.api=async(path,opts)=>{
            if(path==='/api/service-catalog')return {services:[]};
            if(path!='/api/tenants'||opts.method!=='POST')throw Error('Unexpected API');
            posts.push(opts.body); return {tenant:{id:'fixture',name:'Fixture'}};
          };
          window.modal=({body,footer,onOpen})=>{document.body.innerHTML=body+footer;onOpen(document.body,()=>{})};
        }''')
        self.page.add_script_tag(content=self.script)
        self.page.evaluate('addClientModal({refreshTenants:async()=>{}})')
        for name, value in [('name', 'Fixture Client'), ('slug', 'fixture-client'), ('primary_contact_name', 'Fixture'), ('primary_contact_email', 'fixture@example.com')]:
            self.page.locator(f'[name={name}]').fill(value)
        self.website = self.page.locator('[name=website_url]')

    def tearDown(self):
        self.page.close()

    def submit(self):
        self.page.locator('#save-client').click()
        return self.page.evaluate('posts')

    def test_typing_domains_and_full_urls(self):
        for value in ['example.com', 'www.example.com', 'https://example.com', 'http://example.com/Path?q=Hello#Section']:
            with self.subTest(value=value):
                self.website.fill('')
                self.website.press_sequentially(value)
                self.assertEqual(self.website.input_value(), value)
                posts = self.submit()
                expected = value if value.startswith('http') else 'https://' + value
                self.assertEqual(posts[-1]['website_url'], expected)
                self.assertTrue(self.page.evaluate('created'))
                self.page.locator('#save-client').evaluate('(e)=>e.disabled=false')

    def test_paste_normalizes_only_at_submission(self):
        self.website.focus()
        self.page.keyboard.insert_text('www.example.com/contact')
        self.assertEqual(self.website.input_value(), 'www.example.com/contact')
        self.assertEqual(self.submit()[0]['website_url'], 'https://www.example.com/contact')

    def test_invalid_and_incomplete_rejected(self):
        for value in ['https://', 'https:///example.com', 'example', 'bad domain.com', '-bad.com', 'bad-.com', 'example..com', 'ftp://example.com', 'javascript:alert(1)', '//example.com', 'https://user:password@example.com', 'https://example.com:99999']:
            with self.subTest(value=value):
                self.website.fill(value)
                self.assertEqual(self.submit(), [])
                self.assertFalse(self.website.evaluate('(e)=>e.checkValidity()'))

    def test_optional_blank(self):
        self.assertEqual(self.submit()[0]['website_url'], '')

    def test_edit_after_validation_error(self):
        self.website.press_sequentially('https://')
        self.assertEqual(self.submit(), [])
        self.website.press_sequentially('example.com')
        self.website.press('ArrowLeft')
        self.website.press('Backspace')
        self.website.press_sequentially('o')
        self.assertEqual(self.website.input_value(), 'https://example.com')
        self.assertEqual(self.submit()[0]['website_url'], 'https://example.com')

    def test_other_required_validation_preserved(self):
        self.page.locator('[name=primary_contact_email]').fill('invalid')
        self.website.fill('example.com')
        self.assertEqual(self.submit(), [])


if __name__ == '__main__':
    unittest.main()
