"""Auto-discover the pages of a chapter from a single starting URL.

Given a chapter landing page (e.g. .../docs/before-you-deploy.html), find every
sub-page that belongs to it so the caller doesn't have to list pages by hand.

Strategy: a chapter's pages live under the landing page's path prefix — the
landing page ``.../before-you-deploy.html`` owns everything under
``.../before-you-deploy/``. We breadth-first crawl content links, keeping only
pages under that prefix. BFS from the landing page yields a natural reading
order: the landing page first, then its children in the order it lists them,
then their children.
"""

from __future__ import annotations

import sys
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from .extract import extract_content, fetch
from .links import canonical


def _child_prefix(start_url: str) -> str:
    """Path prefix (with trailing slash) that a chapter's sub-pages live under."""
    base = urldefrag(start_url)[0]
    if base.endswith(".html"):
        base = base[: -len(".html")]
    return base.rstrip("/") + "/"


def _under_prefix(url: str, prefix: str) -> bool:
    u, p = urlparse(canonical(url)), urlparse(canonical(prefix))
    return u.netloc == p.netloc and u.path.startswith(p.path.rstrip("/") + "/")


# Extensions that are assets, not content pages. A URL is treated as a page if
# it ends in .html/.htm or has no file extension (a clean/dir URL); anything with
# a different extension (images, PDFs, CSS, ...) must never become a "page".
def _is_page_url(url: str) -> bool:
    tail = urlparse(url).path.rsplit("/", 1)[-1]
    if "." not in tail:
        return True
    return tail.rsplit(".", 1)[-1].lower() in ("html", "htm")


def _fetchable(url: str, timeout: int) -> bool:
    try:
        fetch(url, timeout=timeout)
        return True
    except Exception:
        return False


def _resolve_landing(input_url: str, timeout: int) -> str:
    """Pick a real page to start from. If ``<path>.html`` doesn't exist, fall
    back to the "section landing lives inside its own directory" convention
    (``<path>/<name>.html``) — e.g. entering
    ``.../real-time-reporting`` finds ``.../real-time-reporting/real-time-reporting.html``."""
    if _fetchable(input_url, timeout):
        return input_url
    stem = input_url[:-5] if input_url.endswith(".html") else input_url.rstrip("/")
    name = stem.rsplit("/", 1)[-1]
    alt = f"{stem}/{name}.html"
    if _fetchable(alt, timeout):
        return alt
    return input_url


def _nav_pages(raw_html: str, page_url: str, prefix: str, also: set[str]) -> list[str]:
    """Pages listed in the Just the Docs sidebar nav that belong to this section,
    in reading order (``nav_order``): everything under ``prefix`` plus any URL
    whose canonical form is in ``also`` (the section landing / entered page).
    The nav is the authoritative source of *which* pages a section contains — a
    landing doesn't always link to its children in content. [] if there's no nav."""
    nav = BeautifulSoup(raw_html, "lxml").select_one("nav#site-nav, nav.site-nav, #site-nav")
    if nav is None:
        return []
    ordered: list[str] = []
    seen: set[str] = set()
    for a in nav.find_all("a", href=True):
        full = urldefrag(urljoin(page_url, a["href"]))[0]
        c = canonical(full)
        if c in seen or not _is_page_url(full):
            continue
        if c in also or _under_prefix(full, prefix):
            seen.add(c)
            ordered.append(full)
    return ordered


def discover_pages(input_url: str, *, max_pages: int = 200, timeout: int = 30) -> list[str]:
    """Return the section's page URLs in the site's reading order.

    The section is everything under the entered path's directory prefix. Pages
    and their order come primarily from the Just the Docs sidebar nav (the site's
    real ``nav_order``); a breadth-first content crawl adds any content-linked
    page the nav omits. Unreachable links are skipped with a warning.
    """
    input_url = urldefrag(input_url)[0]
    prefix = _child_prefix(input_url)                     # the section directory
    start = _resolve_landing(input_url, timeout)
    also = {canonical(input_url), canonical(start)}       # landing / entered page

    found: dict[str, str] = {}      # canonical -> url, only pages that LOAD
    nav_urls: list[str] = []        # captured from the first page that has a nav
    seen = set(also)
    queue = [start]
    while queue and len(found) < max_pages:
        url = queue.pop(0)
        try:
            raw = fetch(url, timeout=timeout)
        except Exception as exc:
            print(f"  WARNING: skipping unreachable page {url} ({exc})", file=sys.stderr)
            continue
        if not nav_urls:
            nav_urls = _nav_pages(raw, url, prefix, also)
        found[canonical(url)] = url
        for a in extract_content(raw).find_all("a", href=True):
            target = urldefrag(urljoin(url, a["href"]))[0]
            key = canonical(target)
            if key in seen or not _under_prefix(target, prefix) or not _is_page_url(target):
                continue
            seen.add(key)
            queue.append(target)

    rank = {canonical(u): i for i, u in enumerate(nav_urls)}
    pages: dict[str, str] = dict(found)
    for u in nav_urls:
        pages.setdefault(canonical(u), u)                 # include nav-only pages
    pages.setdefault(canonical(start), start)             # always include the landing

    base = input_url.rsplit("/", 1)[0] + "/"

    def sort_key(u: str):
        c = canonical(u)
        if c in rank:
            return (0, rank[c], "")
        rel = u[len(base):] if u.startswith(base) else u
        return (1, 0, rel)

    return sorted(pages.values(), key=sort_key)


def build_manifest(start_url: str, *, output: str = "review-document.docx",
                   style_reference: str = "styles.docx", **kw) -> dict:
    """Discover pages and return a manifest dict (base_url + relative pages)."""
    urls = discover_pages(start_url, **kw)
    base_url = start_url.rsplit("/", 1)[0] + "/"
    pages = [u[len(base_url):] if u.startswith(base_url) else u for u in urls]
    return {
        "base_url": base_url,
        "output": output,
        "style_reference": style_reference,
        "pages": pages,
    }


def to_yaml(manifest: dict) -> str:
    lines = [
        f"base_url: {manifest['base_url']}",
        f"output: {manifest['output']}",
        f"style_reference: {manifest['style_reference']}",
        "pages:",
    ]
    lines += [f"  - {p}" for p in manifest["pages"]]
    return "\n".join(lines) + "\n"
