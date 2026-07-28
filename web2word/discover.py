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


def discover_pages(start_url: str, *, max_pages: int = 200, timeout: int = 30) -> list[str]:
    """Return absolute page URLs of the chapter in reading order.

    Breadth-first crawl of content links under the chapter's path prefix finds
    every page (completeness). We then sort by path: because "." sorts before
    "/", a parent page (``component-reference.html``) always precedes its
    children (``component-reference/...``), and each subtree stays grouped.
    Sibling order is alphabetical — a stable, predictable default; edit the
    generated manifest if a specific chapter needs a different sequence.
    """
    start_url = urldefrag(start_url)[0]
    prefix = _child_prefix(start_url)

    found: dict[str, str] = {}          # canonical -> url, only pages that LOAD
    seen = {canonical(start_url)}       # everything ever queued (avoid re-queue)
    queue = [start_url]
    while queue and len(found) < max_pages:
        url = queue.pop(0)
        try:
            content = extract_content(fetch(url, timeout=timeout))
        except Exception as exc:
            # A broken/404 link (e.g. a malformed relative link in the source)
            # was queued but doesn't exist. Warn and exclude it rather than
            # letting it abort the whole build later.
            print(f"  WARNING: skipping unreachable page {url} ({exc})", file=sys.stderr)
            continue
        found[canonical(url)] = url     # confirmed to load -> include it
        for a in content.find_all("a", href=True):
            target = urldefrag(urljoin(url, a["href"]))[0]
            key = canonical(target)
            if key in seen or not _under_prefix(target, prefix) or not _is_page_url(target):
                continue
            seen.add(key)
            queue.append(target)

    base = start_url.rsplit("/", 1)[0] + "/"
    # Sort by path relative to base so hierarchy/order is deterministic.
    return sorted(found.values(), key=lambda u: u[len(base):] if u.startswith(base) else u)


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
