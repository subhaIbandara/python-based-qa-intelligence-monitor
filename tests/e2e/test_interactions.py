"""Browser dialogs, modal pop-ups, iframes, new tabs and drag-and-drop."""
import re

import pytest
from playwright.sync_api import expect


def _answer_dialog(page, action, text=None):
    """Answer the next JS dialog; returns a list that receives (type, message)."""
    seen = []

    def handle(dialog):
        seen.append((dialog.type, dialog.message))
        if action == "accept":
            dialog.accept(text) if text is not None else dialog.accept()
        else:
            dialog.dismiss()

    page.once("dialog", handle)
    return seen


# --------------------------------------------------------------- alerts & pop-ups
@pytest.mark.qa("Alerts & pop-ups", 1, "UI")
def test_alert_box(site, page):
    site("/elements/alert/alert")
    seen = _answer_dialog(page, "accept")
    page.click("a.a-button")                # the dialog fires (and is answered) during the click
    assert seen == [("alert", "I am an alert!")], f"dialogs seen: {seen}"


@pytest.mark.qa("Alerts & pop-ups", 2, "UI")
def test_confirm_box_reports_choice(site, page):
    for action, expected in [("dismiss", re.compile("^Cancel$", re.I)), ("accept", re.compile("^Ok$", re.I))]:
        site("/elements/alert/confirm")
        seen = _answer_dialog(page, action)
        page.click("a.a-button")
        assert seen and seen[0][0] == "confirm", f"no confirm dialog (saw {seen})"
        expect(page.locator("#result-text")).to_have_text(expected)


@pytest.mark.qa("Alerts & pop-ups", 3, "UI")
def test_prompt_box_echoes_text(site, page):
    site("/elements/alert/prompt")
    seen = _answer_dialog(page, "accept", "automated learner")
    page.click("a.a-button")
    assert seen and seen[0][0] == "prompt", f"no prompt dialog (saw {seen})"
    expect(page.locator("#result-text")).to_have_text("automated learner")


@pytest.mark.qa("Alerts & pop-ups", 4, "UI")
def test_modal_popup(site, page):
    site("/elements/popup/modal")
    modal = page.locator("#exampleModal")
    expect(modal).to_be_hidden()
    page.click("button[data-bs-target='#exampleModal']")
    expect(modal).to_be_visible()
    modal.locator("#id_checkbox_0").check()
    modal.locator("button[type=submit]").click()
    expect(page.locator("#result-text")).to_have_text("select me or not")
    expect(modal).to_be_hidden()


# --------------------------------------------------- frames, tabs & drag-and-drop
@pytest.mark.qa("Frames, tabs & drag-and-drop", 1, "UI")
def test_iframe_content(site, page):
    site("/elements/iframe/iframe_page")
    frame = page.frame_locator("iframe").first
    expect(frame.get_by_role("heading", name="Album example")).to_be_visible()


@pytest.mark.qa("Frames, tabs & drag-and-drop", 2, "UI")
def test_new_tab_link(site, page):
    site("/elements/new_tab/link")
    link = page.locator("#new-page-link")
    expect(link).to_have_attribute("target", "_blank")
    with page.context.expect_page() as new_tab:
        link.click()
    tab = new_tab.value
    tab.wait_for_load_state()
    expect(tab).to_have_url(re.compile(r"/elements/new_tab/new_page/?$"))
    expect(tab.locator("body")).to_contain_text("I am a new page")
    tab.close()


@pytest.mark.qa("Frames, tabs & drag-and-drop", 3, "UI")
def test_drag_box_onto_drop_zone(site, page):
    site("/elements/dragndrop/boxes")
    target = page.locator("#rect-droppable")
    expect(target).to_contain_text("Drop here")
    page.drag_and_drop("#rect-draggable", "#rect-droppable")
    expect(target).to_contain_text("Dropped!")
