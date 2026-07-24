"""Tie the pipeline together: manifest -> merged HTML -> Pandoc -> .docx."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

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

    def page_urls(self) -> list[str]:
        return [urljoin(self.base_url, p) for p in self.pages]


def build(manifest: Manifest, *, verbose: bool = False) -> Path:
    urls = manifest.page_urls()

    # Build the scope set first so links on page 1 can resolve to page 5.
    scope = ScopeSet()
    slugs: list[str] = []
    for url in urls:
        slug = slugify(url)
        # de-duplicate slugs across chapters
        base_slug, n = slug, 2
        while slug in slugs:
            slug = f"{base_slug}-{n}"
            n += 1
        slugs.append(slug)
        scope.add(url, slug)

    # Fetch, extract, transform each page.
    transformed = []
    for url, rel, slug in zip(urls, manifest.pages, slugs):
        if verbose:
            print(f"  processing {rel}  (slug: {slug})")
        raw = read_local(str(Path(manifest.local_dir) / rel)) if manifest.local_dir else fetch(url)
        soup = extract_content(raw)
        soup = transform_page(soup, page_url=url, page_slug=slug, scope=scope)
        transformed.append(soup)

    merged_html = merge(transformed)

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
