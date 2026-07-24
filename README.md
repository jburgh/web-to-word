# web2word

Convert a set of published web pages (a chapter of a docs site) into a **single
Word document** with **working links** — built for the CDC NBS 7 System Admin
Guide eclearance process.

- Links between pages that are **in the review set** become real Word
  **bookmarks** (clickable in-document jumps).
- Links to anything **outside the set** (other chapters, external sites) become
  **live web hyperlinks**.
- Content, headings, tables, and lists are reproduced; fonts/styles are
  controlled by an optional Word **reference document**.

## Who runs this, and how

There are two ways to use it, depending on who you are.

### For reviewers / non-technical teammates — no install, browser only

1. On GitHub, open the **Actions** tab.
2. Click **Build Word doc** in the left sidebar, then **Run workflow**.
3. **Paste a chapter's landing-page URL** (the tool finds its sub-pages on its
   own) and click the green **Run workflow** button.
4. When the run finishes (~1 min), open it and download the `.docx` from the
   **Artifacts** section at the bottom.

No terminal, no Python, no Pandoc, and **no YAML to edit** — paste a URL and go.
The run also produces a `discovered-manifest.yml` artifact; if you want to keep a
chapter as a named, reusable review set, commit that file to `examples/` and run
it locally with `python -m web2word examples/<name>.yml`.

### For maintainers — locally

See [Usage](#usage) below (requires Pandoc + Python).

## How it works

```
manifest.yml ──> fetch ──> extract (strip chrome) ──> namespace ids
                                                          │
   Word .docx <── pandoc <── merge <── resolve & rewrite links
```

The interesting part is link resolution (`web2word/links.py`). Each page's
element ids are namespaced (`planning--go-live`) so anchors stay unique after
pages are merged, then every `<a href>` is classified against the review set:
in-scope → internal bookmark, everything else → absolute web URL. The many URL
spellings that resolve to the same page (relative, `../` parent-relative,
absolute-path) are all normalized to one canonical key before matching.

## Requirements

- [Pandoc](https://pandoc.org) 3.x on PATH (does the HTML→OOXML heavy lifting,
  including bookmarks and internal hyperlinks)
- Python 3.9+, `pip install -r requirements.txt`

## Usage

```bash
# 1. (once) build a styled reference document resembling the site
python scripts/make_reference.py styles.docx

# 2a. convert a chapter straight from a URL (auto-discovers its sub-pages)
python -m web2word "https://<site>/docs/before-you-deploy.html" -o chapter.docx

#     ...optionally save the discovered page list as a reusable manifest:
python -m web2word "https://<site>/docs/before-you-deploy.html" \
    -o chapter.docx --save-manifest examples/before-you-deploy-chapter.yml

# 2b. or convert a saved manifest (points at styles.docx via style_reference:)
python -m web2word examples/before-you-deploy-chapter.yml -v
```

### Styling

`scripts/make_reference.py` patches Pandoc's default reference document to
resemble the Just the Docs site: system-sans headings/body (Segoe UI), near-black
headings (`#1A1A1A`), CDC-blue underlined hyperlinks (`#005DAA`), Consolas code.
Styling is "similar, not exact" by design; tweak the constants at the top of the
script to adjust. Content text is never altered — only styles.

### What gets cleaned vs. kept

- **Removed:** site chrome (nav, sidebar, footer, search), decorative heading-link
  icons, and Jekyll's auto-generated end-of-page **"Table of contents"** child-page
  list.
- **Kept verbatim:** all authored content, including each page's **"On this page"**
  section TOC.

Chapters are separated by real Word **page breaks** (via `web2word/pagebreak.lua`).

**Images** are rewritten to absolute URLs and embedded in the document, with alt
text preserved. **Fenced code blocks** get a light gray boxed background in
Consolas; inline code stays monospace.

### Manifest

```yaml
base_url: https://jburgh.github.io/CDCgov-NEDSS-SystemAdminGuide-preview/docs/
output: before-you-deploy-chapter.docx
# style_reference: styles.docx   # optional: controls fonts/heading styles
# local_dir: ../site/_site/docs  # optional: read from a local Jekyll build
pages:                            # order = reading order in the document
  - before-you-deploy.html
  - before-you-deploy/planning.html
  # ... every page you want cross-linked internally
```

Any in-scope page listed here gets internal bookmarks; anything not listed
resolves to its live URL. To pull a whole chapter's cross-references inward,
list every page of the chapter.

## Verifying a build

`scripts/verify.py` re-opens the `.docx` and reports internal-link/bookmark
counts and any **dead** internal links (an anchor with no matching bookmark).
