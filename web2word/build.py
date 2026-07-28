"""Tie the pipeline together: manifest -> merged HTML -> Pandoc -> .docx."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from .extract import extract_content, fetch, read_local
from .links import ScopeSet
from .transform import merge, transform_page


def slugify(url: str) -> str:
    """Short readable slug from a page path, e.g. ...before-you-deploy.html -> before-you-deploy."""
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    tail = re.sub(r"\.html?$", "", tail)
    tail = re.sub(r"[^a-zA-Z0-9]+", "-", tail).strip("-").lower()
    return tail or "page"


@dataclass
class Manifest:
    base_url: str
    pages: list[str]          # relative to base_url, in reading order
    output: str = "output.docx"
    style_reference: str | None = None
    local_dir: str | None = None   # if set, read pages from disk instead of HTTP
    public_host: str | None = None  # public origin to rewrite crawl-origin links to

    def page_urls(self) -> list[str]:
        return [urljoin(self.base_url, p) for p in self.pages]


def _fail_on_dead_links(pages: list[tuple[str, "object"]]) -> None:
    """Abort (with an actionable report) if any in-document link points at a
    section anchor that doesn't exist — i.e. a link like `page.html#section`
    where `#section` isn't on that page. Reported in human-readable terms
    (source page, link text, target) rather than the Pandoc-hashed bookmark
    name, so the broken source link can actually be found and fixed."""
    present_ids = {
        el["id"] for _url, soup in pages for el in soup.find_all(attrs={"id": True})
    }
    dead = []
    for url, soup in pages:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("#") and href[1:] not in present_ids:
                slug, _, section = href[1:].partition("--")
                dead.append((url, a.get_text(strip=True), slug, section))
    if not dead:
        return
    lines = ["", f"ERROR: {len(dead)} broken in-document link(s) — the target section does not exist:"]
    for url, text, slug, section in dead:
        page = url.split("/docs/")[-1] if "/docs/" in url else url
        lines.append(f"  - on {page}")
        lines.append(f"      link text : {text!r}")
        lines.append(f"      points to : page '{slug}', section '#{section or '(top)'}' — not found")
    lines.append("")
    lines.append("Fix the anchor in the source markdown (the '#section' must match a heading "
                 "on the target page), then rebuild.")
    raise SystemExit("\n".join(lines))


def build(manifest: Manifest, *, verbose: bool = False) -> Path:
    urls = manifest.page_urls()

    # Load every page first. Skip (with a warning) any that fail to load so a
    # single broken link in the source can't abort the whole document. Skipped
    # pages are also left out of the scope set below, so links to them fall back
    # to external URLs instead of becoming dead in-document bookmarks.
    loaded: list[tuple[str, str, str]] = []   # (url, rel, raw_html)
    for url, rel in zip(urls, manifest.pages):
        try:
            raw = read_local(str(Path(manifest.local_dir) / rel)) if manifest.local_dir else fetch(url)
        except Exception as exc:
            print(f"  WARNING: skipping {rel}: {exc}")
            continue
        loaded.append((url, rel, raw))

    if not loaded:
        raise SystemExit("web2word: no pages could be loaded; nothing to convert.")

    # Build the scope set (from the pages that loaded) so links on page 1 can
    # resolve to page 5.
    scope = ScopeSet()
    if manifest.public_host:
        origin = urlsplit(manifest.base_url)
        scope.rewrite_from = f"{origin.scheme}://{origin.netloc}"
        scope.rewrite_to = manifest.public_host.rstrip("/")
    slugs: list[str] = []
    for url, _rel, _raw in loaded:
        slug = slugify(url)
        # de-duplicate slugs across chapters
        base_slug, n = slug, 2
        while slug in slugs:
            slug = f"{base_slug}-{n}"
            n += 1
        slugs.append(slug)
        scope.add(url, slug)

    # Extract + transform each loaded page.
    transformed = []
    for (url, rel, raw), slug in zip(loaded, slugs):
        if verbose:
            print(f"  processing {rel}  (slug: {slug})")
        soup = extract_content(raw)
        soup = transform_page(soup, page_url=url, page_slug=slug, scope=scope)
        transformed.append((url, soup))

    _fail_on_dead_links(transformed)

    merged_html = merge([soup for _url, soup in transformed])

    # Wrap for a clean standalone document.
    doc = f"<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>{merged_html}</body></html>"

    out = Path(manifest.output)
    lua_filter = Path(__file__).with_name("pagebreak.lua")
    cmd = [
        "pandoc",
        "-f", "html",
        "-t", "docx",
        "--lua-filter", str(lua_filter),
        "-o", str(out),
    ]
    if manifest.style_reference:
        cmd += ["--reference-doc", manifest.style_reference]

    if verbose:
        print(f"  running: {' '.join(cmd)}")
    subprocess.run(cmd, input=doc.encode("utf-8"), check=True)
    return out
