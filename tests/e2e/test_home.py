"""Home page: availability, title, rendering, JS health, performance budget, phone layout."""
import re

import pytest
from playwright.sync_api import expect

HOME_BUDGET_MS = 3000
SITE_TITLE = re.compile(r"QA Practice")


@pytest.mark.qa("Home page", 1, "API")
def test_home_responds_ok(api):
    resp = api.get("/")
    assert resp.status == 200, f"GET / returned {resp.status}"
    assert "text/html" in resp.headers.get("content-type", "")
    title = re.search(r"<title[^>]*>(.*?)</title>", resp.text(), re.S | re.I)
    assert title and SITE_TITLE.search(title.group(1)), \
        f"unexpected title: {title.group(1).strip() if title else None!r}"


@pytest.mark.qa("Home page", 2, "API")
def test_home_response_time_budget(api):
    resp = api.get("/")
    assert resp.status == 200
    assert resp.elapsed_ms < HOME_BUDGET_MS, f"home page took {resp.elapsed_ms:.0f} ms (budget {HOME_BUDGET_MS} ms)"


@pytest.mark.qa("Home page", 3, "UI")
def test_home_renders(site, page):
    site("/")
    expect(page).to_have_title(SITE_TITLE)
    expect(page.locator("h1").first).to_be_visible()
    for group in ("Single UI Elements", "Forms"):                              # sidebar menu
        expect(page.locator("li.has-sub > a", has_text=group)).to_be_visible()
    expect(page.locator("footer").first).to_be_attached()


@pytest.mark.qa("Home page", 4, "UI")
def test_home_has_no_js_errors(site, page):
    site("/")
    page.wait_for_timeout(1500)            # let deferred scripts run
    assert not site.errors, f"JavaScript errors on load: {site.errors[:3]}"


@pytest.mark.qa("Home page", 5, "UI")
def test_home_fits_phone_screen(site, page):
    page.set_viewport_size({"width": 390, "height": 844})
    site("/")
    expect(page.locator("h1").first).to_be_visible()
    scroll_width = page.evaluate("() => document.documentElement.scrollWidth")
    assert scroll_width <= 391, f"page is {scroll_width}px wide on a 390px screen (horizontal scroll)"
