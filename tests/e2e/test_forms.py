"""Practice form (student registration) and the contact form.

The practice form is meant to be submitted, so the suite fills and sends it. The contact form
is only checked up to validation: sending it would message the real site owner.
"""
import re

import pytest
from playwright.sync_api import expect

STUDENT = {"#firstName": "Ada", "#lastName": "Lovelace", "#userEmail": "ada@example.com",
           "#userNumber": "0123456789"}


def _dropdown(page, index):
    """The practice form replaces its <select>s with custom dropdowns (0 = state, 1 = city)."""
    return page.locator(".custom-dropdown").nth(index)


# ------------------------------------------------------------------- practice form
@pytest.mark.qa("Practice form", 1, "API")
def test_practice_form_page(api):
    resp = api.get("/forms/practice-form")
    assert resp.status == 200, f"/forms/practice-form returned {resp.status}"
    html = resp.text()
    assert "<form" in html.lower(), "practice form page has no <form>"
    assert "csrfmiddlewaretoken" in html, "practice form has no CSRF token"


@pytest.mark.qa("Practice form", 2, "UI")
def test_practice_form_submits(site, page):
    site("/forms/practice-form")
    for selector, value in STUDENT.items():
        page.fill(selector, value)
    page.locator("label[for=gender_1]").click()             # Female
    page.click("#submit-id-submit")
    modal = page.locator("#resultsModal")
    expect(modal).to_be_visible()
    expect(modal.locator("#resultsModalLabel")).to_contain_text("Thanks for submitting")
    table = page.locator("#resultsTable")
    for text in ("Ada Lovelace", "ada@example.com", "Female", "0123456789"):
        expect(table).to_contain_text(text)


@pytest.mark.qa("Practice form", 3, "UI")
def test_practice_form_requires_fields(site, page):
    site("/forms/practice-form")
    page.click("#submit-id-submit")
    page.wait_for_timeout(500)
    missing = page.evaluate("() => [...document.querySelectorAll('form :invalid')].map(e => e.id || e.name)")
    for field in ("firstName", "lastName", "userNumber"):
        assert field in missing, f"{field} is not flagged as required (invalid fields: {missing})"
    expect(page.locator("#resultsModal")).to_be_hidden()


@pytest.mark.qa("Practice form", 4, "UI")
def test_state_fills_city_list(site, page):
    site("/forms/practice-form")
    state, city = _dropdown(page, 0), _dropdown(page, 1)
    expect(city.locator(".custom-dropdown-control")).to_have_css("pointer-events", "none")   # disabled
    state.locator(".custom-dropdown-control").click()
    state.locator(".custom-dropdown-option[data-value='Haryana']").click()
    expect(page.locator("#state")).to_have_value("Haryana")
    expect(city.locator(".custom-dropdown-control")).not_to_have_css("pointer-events", "none")
    options = city.locator(".custom-dropdown-option")
    expect(options).to_have_text(["Karnal", "Panipat"])
    city.locator(".custom-dropdown-control").click()
    options.filter(has_text="Panipat").click()
    expect(city.locator(".selected-value")).to_have_text("Panipat")


@pytest.mark.qa("Practice form", 5, "UI")
def test_subjects_autocomplete(site, page):
    site("/forms/practice-form")
    page.fill("#subjectsAutocomplete", "Ma")
    suggestion = page.locator("#subjectsSuggestions .suggestion-item", has_text="Maths")
    expect(suggestion).to_be_visible()
    suggestion.click()
    expect(page.locator("#subjectsTags")).to_contain_text("Maths")
    expect(page.locator("#subjectsInput")).to_have_value(re.compile("Maths"))


# -------------------------------------------------------------------- contact form
@pytest.mark.qa("Contact form", 1, "API")
def test_contact_page_has_form(api):
    resp = api.get("/contact/")
    assert resp.status == 200, f"/contact/ returned {resp.status}"
    assert "<form" in resp.text().lower(), "contact page has no <form>"


@pytest.mark.qa("Contact form", 2, "UI")
def test_contact_message_required(site, page):
    site("/contact/")
    posts = []
    page.on("request", lambda r: r.method == "POST" and "/contact" in r.url and posts.append(r.url))
    page.fill("#id_email", "learner@example.com")              # message left empty on purpose
    page.click("#submit-id-submit")
    page.wait_for_timeout(500)
    assert page.locator("#id_message").evaluate("e => e.validity.valueMissing"), "message is not required"
    assert not posts, "contact form was sent without a message"
