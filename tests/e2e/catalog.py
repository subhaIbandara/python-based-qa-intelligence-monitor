"""Feature / requirement catalog for the site under test (https://www.qa-practice.com).

qa-practice.com is a playground of UI elements (inputs, buttons, checkboxes, selects, dialogs,
drag-and-drop, iframes, new tabs, pop-ups) plus a practice form and a contact form.

Coverage on the dashboard = requirements with at least one automated test ÷ all requirements
listed here. Requirements marked manual (automated=False) are deliberately not automated and
show up as coverage gaps — e.g. sending the contact form would message the real site owner.
"""

FEATURES = {
    # name: (criticality 1-5, {req_no: (layer, description, automated)})
    "Home page": (5, {
        1: ("API", "Home page responds 200 over HTTPS with the QA Practice title", True),
        2: ("API", "Home page responds within the 3 s budget", True),
        3: ("UI", "Heading, sidebar menu and footer render in the browser", True),
        4: ("UI", "No JavaScript errors on load", True),
        5: ("UI", "Fits a 390 px phone screen without horizontal scrolling", True),
    }),
    "Navigation": (4, {
        1: ("UI", "Sidebar lists every element section and the practice form", True),
        2: ("API", "Every sidebar link on the home page resolves", True),
        3: ("UI", "Clicking a sidebar link opens that section", True),
        4: ("API", "Unknown paths return 404", True),
    }),
    "Inputs & text areas": (4, {
        1: ("UI", "Text input echoes a valid value after submit", True),
        2: ("UI", "Text input rejects invalid characters and too-short values", True),
        3: ("UI", "Email field rejects a malformed address and accepts a valid one", True),
        4: ("UI", "Password field submits its value", True),
        5: ("UI", "Single and multiple text areas echo their content", True),
    }),
    "Buttons": (3, {
        1: ("UI", "Simple button submits", True),
        2: ("UI", "Link styled as a button submits", True),
        3: ("UI", "Disabled button stays disabled until enabled from the select", True),
    }),
    "Checkboxes & selects": (3, {
        1: ("UI", "Single checkbox submits its value", True),
        2: ("UI", "Multiple checkboxes submit only the checked values", True),
        3: ("UI", "Single select submits the chosen option", True),
        4: ("UI", "Multiple selects submit every choice", True),
    }),
    "Alerts & pop-ups": (4, {
        1: ("UI", "Alert box shows its message and can be accepted", True),
        2: ("UI", "Confirm box reports OK and Cancel", True),
        3: ("UI", "Prompt box echoes the entered text", True),
        4: ("UI", "Modal pop-up opens, submits its form and closes", True),
    }),
    "Frames, tabs & drag-and-drop": (3, {
        1: ("UI", "Iframe content loads and can be read", True),
        2: ("UI", "New-tab link opens the target page in a new tab", True),
        3: ("UI", "Box can be dragged onto the drop zone", True),
        4: ("UI", "Images can be dragged onto the drop zone", False),
    }),
    "Practice form": (5, {
        1: ("API", "Practice form page is available with a CSRF-protected form", True),
        2: ("UI", "Submitting the required fields shows them in the results modal", True),
        3: ("UI", "Submitting an empty form is blocked by required-field validation", True),
        4: ("UI", "Choosing a state fills and enables the city list", True),
        5: ("UI", "Subjects autocomplete suggests and adds matching subjects", True),
        6: ("UI", "Date-of-birth picker selects a date", False),
        7: ("UI", "Uploaded picture is reported in the results", False),
    }),
    "Contact form": (4, {
        1: ("API", "Contact page is available and contains a form", True),
        2: ("UI", "The message is required before the form can be sent", True),
        3: ("UI", "Sending a message reaches the site owner (not automated: would message the real owner)",
            False),
    }),
    "SEO & crawlability": (2, {
        1: ("API", "robots.txt is served with crawler rules", True),
        2: ("API", "sitemap.xml is valid and lists the site's pages", True),
        3: ("API", "Sitemap URLs use the canonical https host", True),
    }),
    "Security headers": (4, {
        1: ("API", "HTTP redirects permanently to HTTPS", True),
        2: ("API", "HSTS header is set", True),
        3: ("API", "Clickjacking and MIME-sniffing protections are set", True),
    }),
}

# End-to-end learner journeys. Each step is a (feature, requirement no.) above.
# A use case is fully covered when every step has an automated test that ran.
USE_CASES = {
    "Practise basic form controls": (4, "Open an element page and submit each basic control", [
        ("Home page", 1), ("Navigation", 3), ("Inputs & text areas", 1), ("Buttons", 1),
        ("Checkboxes & selects", 1), ("Checkboxes & selects", 3)]),
    "Validate user input": (4, "Bad or missing input is rejected with a clear message", [
        ("Inputs & text areas", 2), ("Inputs & text areas", 3), ("Practice form", 3), ("Contact form", 2)]),
    "Handle browser dialogs and pop-ups": (3, "Work with alert, confirm, prompt and modal windows", [
        ("Alerts & pop-ups", 1), ("Alerts & pop-ups", 2), ("Alerts & pop-ups", 3), ("Alerts & pop-ups", 4)]),
    "Complete the practice form": (5, "Fill every field of the practice form and submit it", [
        ("Home page", 1), ("Navigation", 1), ("Practice form", 1), ("Practice form", 4),
        ("Practice form", 5), ("Practice form", 6), ("Practice form", 7), ("Practice form", 2)]),
    "Work across frames and tabs": (3, "Reach content inside iframes, new tabs and drag targets", [
        ("Frames, tabs & drag-and-drop", 1), ("Frames, tabs & drag-and-drop", 2),
        ("Frames, tabs & drag-and-drop", 3), ("Frames, tabs & drag-and-drop", 4)]),
    "Report a bug to the site owner": (3, "Find the contact page and send a message", [
        ("Navigation", 2), ("Contact form", 1), ("Contact form", 2), ("Contact form", 3)]),
    "Be found via search engines": (2, "Crawlers can discover and index the canonical pages", [
        ("Home page", 1), ("SEO & crawlability", 1), ("SEO & crawlability", 2), ("SEO & crawlability", 3)]),
    "Browse securely": (4, "Visitors are always on HTTPS with browser protections", [
        ("Security headers", 1), ("Security headers", 2), ("Security headers", 3)]),
    "Use the site on a phone": (3, "Render and read the site on a small screen", [
        ("Home page", 3), ("Home page", 5)]),
}
