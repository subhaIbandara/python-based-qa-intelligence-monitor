"""Navigation: the sidebar menu lists every section, its links resolve and work when clicked."""
import re

import pytest
from playwright.sync_api import expect

# Sidebar section → the path its link points to on the home page
SECTIONS = {
    "Inputs": "/elements/input",
    "Buttons": "/elements/button",
    "Checkbox": "/elements/checkbox",
    "Select": "/elements/select",
    "New tab": "/elements/new_tab",
    "Text area": "/elements/textarea",
    "Alerts": "/elements/alert",
    "Drag and Drop": "/elements/dragndrop",
    "Iframes": "/elements/iframe/iframe_page",
    "Pop-Up": "/elements/popup",
    "Practice Form": "/forms/practice-form",
}


MENU_GROUPS = ("Single UI Elements", "Forms")       # collapsible sidebar groups


def _menu_links(html):
    return sorted(set(re.findall(r'href=["\'](/(?:elements|forms)/[^"\'#?]*)["\']', html)))


def _open_menu(page, group):
    toggle = page.locator("li.has-sub > a", has_text=group)
    expect(toggle).to_be_visible()
    toggle.click()


@pytest.mark.qa("Navigation", 1, "UI")
def test_sidebar_lists_all_sections(site, page):
    site("/")
    for group in MENU_GROUPS:
        _open_menu(page, group)
    menu = page.locator("li.has-sub .sub-menu")
    for name, href in SECTIONS.items():
        expect(menu.locator(f"a[href='{href}']"), f"sidebar section {name!r}").to_be_visible()


@pytest.mark.qa("Navigation", 2, "API")
def test_sidebar_links_resolve(api):
    links = _menu_links(api.get("/").text())
    absent = [p for p in SECTIONS.values() if p not in links]
    assert not absent, f"home page no longer links to {absent}"
    broken = {}
    for path in links:
        try:
            status = api.get(path, max_redirects=5).status
        except Exception as err:   # e.g. redirect loop
            status = str(err).splitlines()[0]
        if status != 200:
            broken[path] = status
    assert not broken, f"{len(broken)} of {len(links)} menu links not resolving: {broken}"


@pytest.mark.qa("Navigation", 3, "UI")
def test_click_through_to_section(site, page):
    site("/")
    _open_menu(page, "Forms")
    page.locator(".sub-menu a[href='/forms/practice-form']").click()
    expect(page).to_have_url(re.compile(r"/forms/practice-form/?$"))
    expect(page).to_have_title(re.compile("Practice Form"))
    expect(page.locator("#firstName")).to_be_visible()


@pytest.mark.qa("Navigation", 4, "API")
def test_unknown_path_returns_404(api):
    resp = api.get("/this-page-does-not-exist-qa-suite/")
    assert resp.status == 404, f"unknown path returned {resp.status}, expected 404"
