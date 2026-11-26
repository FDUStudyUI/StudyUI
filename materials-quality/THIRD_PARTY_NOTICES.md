# Third-party notices

## LFX runtime

StudyUI's workflow canvas, component base classes and execution runtime build on
the LFX package. The bundled canvas frontend assets come from the corresponding
vendor runtime distribution.

- Package: [lfx](https://pypi.org/project/lfx/)
- License: MIT
- Copyright: respective LFX authors; the installed distribution ships the full license text.

## DeepSeek Harness

StudyUI's chat presentation adapts interaction patterns and component styling from DeepSeek Harness, including compact tool rows, per-turn token usage, composer statistics, context occupancy, and stable incremental conversation rendering.

- Project: [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)
- License: MIT
- Copyright: Copyright (c) 2026 DeepSeek

MIT License

Copyright (c) 2026 DeepSeek

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## MatOS tool catalog

StudyUI's optional MatOS integration reuses tool names, descriptions,
permissions and JSON input schemas from the MatOS benchmark-minimal
distribution. It does not bundle MatOS Python source code, and it delegates
execution to a user-installed `matos` CLI.

- Project: [DingyangLyu/MatOS](https://github.com/DingyangLyu/MatOS)
- License: PolyForm Noncommercial License 1.0.0
- License URL: <https://polyformproject.org/licenses/noncommercial/1.0.0/>
- Required Notice: Copyright 2026 The MatOS Authors (https://github.com/DingyangLyu/MatOS)
- Source snapshot: commit `a50fd7613346a59f13e87a8bc368d0cec048585d` (2026-10-25)
- Adapted catalog: `src/materials_quality/matos/catalog_data.json`
- Generator: `scripts/build_matos_catalog.py`
- Integration note: `../docs/matos-integration.md`

The full PolyForm Noncommercial 1.0.0 text is available at the license URL
above and in the MatOS repository's `LICENSE` file.
