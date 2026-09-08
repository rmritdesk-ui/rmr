"""One browser lifecycle shared by the Phase 3 and Phase 4 regression gates."""
import pytest
from playwright.sync_api import sync_playwright


@pytest.fixture(scope='session')
def browser():
    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        yield browser
        browser.close()
