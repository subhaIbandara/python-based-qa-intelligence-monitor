"""Crawlability and transport / browser security headers."""
import re
from urllib.parse import urlparse
from xml.etree import ElementTree

import pytest

SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


@pytest.mark.qa("SEO & crawlability", 1, "API")
def test_robots_txt(api):
    resp = api.get("/robots.txt")
    assert resp.status == 200, f"/robots.txt returned {resp.status}"
    assert re.search(r"^User-agent:", resp.text(), re.M | re.I), "robots.txt has no User-agent rules"


def _locs(body):
    return [el.text.strip() for el in ElementTree.fromstring(body).iter(f"{SITEMAP_NS}loc") if el.text]


def _sitemap_urls(api):
    """Page URLs from /sitemap.xml, following a sitemap index into its child sitemaps."""
    resp = api.get("/sitemap.xml")
    assert resp.status == 200, f"/sitemap.xml returned {resp.status}"
    root = ElementTree.fromstring(resp.body())
    if root.tag != f"{SITEMAP_NS}sitemapindex":
        return _locs(resp.body())
    urls = []
    for child in _locs(resp.body()):
        sub = api.get(child)
        assert sub.status == 200, f"child sitemap {child} returned {sub.status}"
        urls += _locs(sub.body())
    return urls


@pytest.mark.qa("SEO & crawlability", 2, "API")
def test_sitemap_is_valid(api):
    urls = _sitemap_urls(api)
    assert len(urls) >= 10, f"sitemap lists only {len(urls)} URLs"


@pytest.mark.qa("SEO & crawlability", 3, "API")
def test_sitemap_uses_canonical_https(api, base_url_str):
    base = urlparse(base_url_str)
    urls = _sitemap_urls(api)
    off = [u for u in urls if (urlparse(u).scheme, urlparse(u).netloc) != (base.scheme, base.netloc)]
    assert not off, (f"{len(off)} of {len(urls)} sitemap URLs are not on {base.scheme}://{base.netloc} "
                     f"(e.g. {off[0]})")


@pytest.mark.qa("Security headers", 1, "API")
def test_http_redirects_to_https(api, base_url_str):
    host = urlparse(base_url_str).netloc
    resp = api.get(f"http://{host}/", max_redirects=0)
    assert resp.status in (301, 308), f"http:// returned {resp.status}, expected a permanent redirect"
    assert resp.headers.get("location", "").startswith("https://"), resp.headers.get("location")


@pytest.mark.qa("Security headers", 2, "API")
def test_hsts_header(api):
    hsts = api.get("/").headers.get("strict-transport-security", "")
    m = re.search(r"max-age=(\d+)", hsts)
    assert m and int(m.group(1)) >= 15_552_000, f"HSTS missing or shorter than 180 days: {hsts!r}"


@pytest.mark.qa("Security headers", 3, "API")
def test_clickjacking_and_sniffing_protection(api):
    h = api.get("/").headers
    assert h.get("x-content-type-options", "").lower() == "nosniff"
    frame_ok = h.get("x-frame-options", "").lower() in ("deny", "sameorigin") or \
        "frame-ancestors" in h.get("content-security-policy", "")
    assert frame_ok, "no X-Frame-Options or CSP frame-ancestors"
