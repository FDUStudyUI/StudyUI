# Bundled browser dependencies

These assets are served locally by StudyUI. Rendering does not contact a CDN.

| Package | Version | License | Upstream |
| --- | --- | --- | --- |
| markdown-it | 15.0.3 | MIT | https://github.com/markdown-it/markdown-it |
| KaTeX | 0.19.1 | MIT | https://github.com/KaTeX/KaTeX |
| DOMPurify | 3.4.17 | Apache-2.0 OR MPL-2.0 | https://github.com/cure53/DOMPurify |

`manifest.json` records each npm registry tarball URL, its verified SHA-512 integrity and each shipped file's SHA-256. License files are included in their package directories. The markdown-it UMD browser bundle is renamed from `dist/browser/markdown-it.umd.min.js` to `markdown-it.min.js`; its contents are unchanged. KaTeX uses its WOFF2 fonts on the supported Chromium browsers. No dependency is fetched at runtime.

To update, obtain an explicit version's metadata from `https://registry.npmjs.org/<package>/<version>`, verify the tarball against `dist.integrity`, copy only the browser bundle, CSS, WOFF2 fonts and license files, then regenerate the file hashes. Run `tests/test_agent_rich_rendering.py` and the complete browser suite before accepting new assets. Do not replace vendored files with unpinned CDN URLs.

Rendering uses markdown-it with raw HTML disabled, DOMPurify sanitization, and KaTeX with `trust: false`, expansion and size limits. Untrusted images become explicit links rather than automatic network requests. Invalid mathematics remains readable as source LaTeX. Copying or exporting an answer uses its original Markdown, preserving formulas and code.
