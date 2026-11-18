"""Single UI elements: inputs, text areas, buttons, checkboxes and selects.

Every element page posts its form back to the site, which re-renders the page with the
submitted value in #result-text (or a validation message under the field).
"""
import pytest
from playwright.sync_api import expect


def _result(page):
    return page.locator("#result-text")


# ------------------------------------------------------------- inputs & text areas
@pytest.mark.qa("Inputs & text areas", 1, "UI")
def test_text_input_echoes_value(site, page):
    site("/elements/input/simple")
    page.fill("#id_text_string", "qa_practice-1")
    page.press("#id_text_string", "Enter")
    expect(_result(page)).to_have_text("qa_practice-1")


@pytest.mark.qa("Inputs & text areas", 2, "UI")
def test_text_input_validation(site, page):
    error = page.locator("#error_1_id_text_string")
    for value, message in [("has space", "valid string"), ("a", "2 or more characters")]:
        site("/elements/input/simple")
        page.fill("#id_text_string", value)
        page.press("#id_text_string", "Enter")
        expect(error).to_contain_text(message)
        expect(_result(page)).to_have_count(0)


@pytest.mark.qa("Inputs & text areas", 3, "UI")
def test_email_field_validation(site, page):
    site("/elements/input/email")
    page.fill("#id_email", "not-an-email")
    page.press("#id_email", "Enter")
    expect(page.locator("#error_1_id_email")).to_contain_text("valid email")
    page.fill("#id_email", "learner@example.com")
    page.press("#id_email", "Enter")
    expect(_result(page)).to_have_text("learner@example.com")


@pytest.mark.qa("Inputs & text areas", 4, "UI")
def test_password_field_submits(site, page):
    site("/elements/input/passwd")
    expect(page.locator("#id_password")).to_have_attribute("type", "password")
    page.fill("#id_password", "Pr4ctice!pass")
    page.press("#id_password", "Enter")
    expect(_result(page)).to_have_text("Pr4ctice!pass")


@pytest.mark.qa("Inputs & text areas", 5, "UI")
def test_text_areas_echo_content(site, page):
    site("/elements/textarea/single")
    page.fill("#id_text_area", "first line\nsecond line")
    page.click("#submit-id-submit")
    expect(_result(page)).to_contain_text("first line")
    expect(_result(page)).to_contain_text("second line")

    site("/elements/textarea/textareas")
    chapters = {"#id_first_chapter": "chapter one", "#id_second_chapter": "chapter two",
                "#id_third_chapter": "chapter three"}
    for selector, text in chapters.items():
        page.fill(selector, text)
    page.click("#submit-id-submit")
    result = page.locator("#result")
    for text in chapters.values():                  # the site capitalises each chapter
        expect(result).to_contain_text(text, ignore_case=True)


# ------------------------------------------------------------------------ buttons
@pytest.mark.qa("Buttons", 1, "UI")
def test_simple_button_submits(site, page):
    site("/elements/button/simple")
    page.click("#submit-id-submit")
    expect(_result(page)).to_have_text("Submitted")


@pytest.mark.qa("Buttons", 2, "UI")
def test_link_button_submits(site, page):
    site("/elements/button/like_a_button")
    page.click("a.a-button")
    expect(_result(page)).to_have_text("Submitted")


@pytest.mark.qa("Buttons", 3, "UI")
def test_disabled_button_until_enabled(site, page):
    site("/elements/button/disabled")
    button = page.locator("#submit-id-submit")
    expect(button).to_be_disabled()
    page.select_option("#id_select_state", "enabled")
    expect(button).to_be_enabled()
    button.click()
    expect(_result(page)).to_have_text("Submitted")


# ------------------------------------------------------------ checkboxes & selects
@pytest.mark.qa("Checkboxes & selects", 1, "UI")
def test_single_checkbox_submits(site, page):
    site("/elements/checkbox/single_checkbox")
    page.check("#id_checkbox_0")
    page.click("#submit-id-submit")
    expect(_result(page)).to_have_text("select me or not")


@pytest.mark.qa("Checkboxes & selects", 2, "UI")
def test_multiple_checkboxes_submit_checked_only(site, page):
    site("/elements/checkbox/mult_checkbox")
    page.check("#id_checkboxes_0")
    page.check("#id_checkboxes_2")
    page.click("#submit-id-submit")
    expect(_result(page)).to_have_text("one, three")


@pytest.mark.qa("Checkboxes & selects", 3, "UI")
def test_single_select_submits(site, page):
    site("/elements/select/single_select")
    page.select_option("#id_choose_language", label="Python")
    page.click("#submit-id-submit")
    expect(_result(page)).to_have_text("Python")


@pytest.mark.qa("Checkboxes & selects", 4, "UI")
def test_multiple_selects_submit(site, page):
    site("/elements/select/mult_select")
    choices = {"#id_choose_the_place_you_want_to_go": "Sea", "#id_choose_how_you_want_to_get_there": "Car",
               "#id_choose_when_you_want_to_go": "Today"}
    for selector, label in choices.items():
        page.select_option(selector, label=label)
    page.click("#submit-id-submit")
    expect(_result(page)).to_have_text("to go by car to the sea today")
