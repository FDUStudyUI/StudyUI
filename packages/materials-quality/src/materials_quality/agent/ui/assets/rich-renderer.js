/* StudyUI Markdown rendering. Dependencies are shipped locally; no runtime CDN. */
(() => {
  'use strict';
  const MAX_SOURCE = 250000;
  const safeURL = value => {
    try {
      const url = new URL(value, location.href);
      return ['http:', 'https:', 'mailto:'].includes(url.protocol) ? url.href : null;
    } catch (_) { return null; }
  };
  const md = window.markdownit({html: false, linkify: true, breaks: false, typographer: false});
  const escape = md.utils.escapeHtml;

  function mathHTML(source, display) {
    const cls = display ? 'math-block' : 'math-inline';
    try {
      const rendered = window.katex.renderToString(source, {
        displayMode: display, throwOnError: true, trust: false,
        strict: 'error', maxExpand: 500, maxSize: 20, output: 'htmlAndMathml',
      });
      return `<span class="${cls}">${rendered}</span>`;
    } catch (_) {
      return `<code class="math-error ${cls}" title="公式语法暂不支持；显示原始 LaTeX">${escape(source)}</code>`;
    }
  }

  function escapedAt(text, pos) {
    let count = 0;
    while (pos > 0 && text[--pos] === '\\') count++;
    return count % 2 === 1;
  }

  // Token rules run after code-span recognition; mathematics in code stays literal.
  md.inline.ruler.before('escape', 'studyui_math', (state, silent) => {
    const pos = state.pos, source = state.src;
    let open, close, display = false;
    if (source.startsWith('\\(', pos)) { open = '\\('; close = '\\)'; }
    else if (source.startsWith('\\[', pos)) { open = '\\['; close = '\\]'; display = true; }
    else if (source.startsWith('$$', pos)) { open = '$$'; close = '$$'; display = true; }
    else if (source[pos] === '$' && !escapedAt(source, pos)) {
      open = close = '$';
      if (/\s/.test(source[pos + 1] || ' ')) return false;
    } else return false;
    let end = source.indexOf(close, pos + open.length);
    while (end >= 0 && escapedAt(source, end)) end = source.indexOf(close, end + close.length);
    if (end < 0 || end === pos + open.length) return false;
    if (open === '$' && (/\s/.test(source[end - 1]) || /\d/.test(source[end + 1] || ''))) return false;
    if (!silent) {
      const token = state.push('studyui_math', '', 0);
      token.content = source.slice(pos + open.length, end);
      token.meta = {display};
    }
    state.pos = end + close.length;
    return true;
  });
  md.renderer.rules.studyui_math = (tokens, index) => mathHTML(tokens[index].content, tokens[index].meta.display);

  md.block.ruler.before('fence', 'studyui_math_block', (state, startLine, endLine, silent) => {
    const start = state.bMarks[startLine] + state.tShift[startLine];
    const first = state.src.slice(start, state.eMarks[startLine]);
    const open = first.startsWith('$$') ? '$$' : first.startsWith('\\[') ? '\\[' : null;
    if (!open || state.sCount[startLine] - state.blkIndent >= 4) return false;
    const close = open === '$$' ? '$$' : '\\]';
    let end = startLine, content = first.slice(open.length), closeAt = content.indexOf(close);
    while (closeAt < 0 && ++end < endLine) {
      content += '\n' + state.src.slice(state.bMarks[end] + state.tShift[end], state.eMarks[end]);
      closeAt = content.indexOf(close);
    }
    if (closeAt < 0 || content.slice(closeAt + close.length).trim()) return false;
    if (silent) return true;
    const token = state.push('studyui_math', '', 0);
    token.block = true;
    token.content = content.slice(0, closeAt).trim();
    token.meta = {display: true};
    token.map = [startLine, end + 1];
    state.line = end + 1;
    return true;
  }, {alt: ['paragraph', 'reference', 'blockquote', 'list']});

  const linkOpen = md.renderer.rules.link_open || ((tokens, index, options, env, self) =>
    self.renderToken(tokens, index, options));
  md.renderer.rules.link_open = (tokens, index, options, env, self) => {
    const token = tokens[index], href = safeURL(token.attrGet('href') || '');
    if (!href) token.attrSet('href', '#');
    else token.attrSet('href', href);
    token.attrSet('target', '_blank');
    token.attrSet('rel', 'noopener noreferrer');
    if (href && /https:\/\/(?:doi\.org|arxiv\.org)\//.test(href)) token.attrSet('class', 'doi-badge');
    return linkOpen(tokens, index, options, env, self);
  };
  // Do not transmit a research session's reading behavior to arbitrary image hosts.
  md.renderer.rules.image = (tokens, index) => {
    const token = tokens[index], label = token.content || '图片', href = safeURL(token.attrGet('src') || '');
    return href
      ? `<a class="image-source-link" href="${escape(href)}" target="_blank" rel="noopener noreferrer">图片：${escape(label)}（打开原图）</a>`
      : `<span>图片：${escape(label)}</span>`;
  };

  async function copyText(text, button) {
    try {
      await navigator.clipboard.writeText(text);
      if (button) { const old = button.textContent; button.textContent = '已复制'; setTimeout(() => {button.textContent = old;}, 1600); }
      if (typeof window.toast === 'function') window.toast('已复制原始文本');
      return true;
    } catch (_) {
      if (typeof window.toast === 'function') window.toast('复制失败，请选中文本后复制');
      return false;
    }
  }

  function render(raw, options = {}) {
    const source = String(raw ?? ''), container = document.createElement('div');
    container.className = 'rich-content';
    container.markdownSource = source;
    container.setAttribute('aria-busy', options.streaming ? 'true' : 'false');
    if (source.length > MAX_SOURCE) {
      const note = document.createElement('p');
      note.className = 'render-warning';
      note.textContent = '回答较长，显示纯文本；复制和导出仍保留完整原文。';
      const plain = document.createElement('pre'); plain.className = 'rich-plain'; plain.textContent = source;
      container.append(note, plain);
      return container;
    }
    container.innerHTML = window.DOMPurify.sanitize(md.render(source), {
      FORBID_TAGS: ['img', 'iframe', 'object', 'embed', 'style', 'script', 'form', 'input'],
      ADD_ATTR: ['target'],
    });
    for (const table of container.querySelectorAll('table')) {
      const wrap = document.createElement('div'); wrap.className = 'rich-table-wrap';
      wrap.tabIndex = 0; wrap.setAttribute('role', 'region'); wrap.setAttribute('aria-label', '数据表格，可横向滚动');
      table.classList.add('rich-table'); table.replaceWith(wrap); wrap.append(table);
    }
    for (const pre of container.querySelectorAll('pre')) {
      const code = pre.querySelector('code'); if (!code) continue;
      const language = Array.from(code.classList).find(cls => cls.startsWith('language-'))?.slice(9) || 'text';
      const wrapper = document.createElement('div'); wrapper.className = 'code-block';
      const head = document.createElement('div'); head.className = 'code-header';
      const label = document.createElement('span'); label.className = 'code-lang'; label.textContent = language;
      const actions = document.createElement('div'); actions.className = 'code-actions';
      const copy = document.createElement('button'); copy.type = 'button'; copy.className = 'code-btn';
      copy.textContent = '复制代码'; copy.addEventListener('click', () => copyText(code.textContent, copy));
      actions.append(copy);
      if (!options.streaming && ['python', 'py'].includes(language.toLowerCase())) {
        const draft = document.createElement('button'); draft.type = 'button'; draft.className = 'code-btn';
        draft.textContent = '保存代码审核草稿';
        draft.addEventListener('click', () => window.insertCanvasNode?.(code.textContent, language));
        actions.append(draft);
      }
      head.append(label, actions); pre.replaceWith(wrapper); wrapper.append(head, pre);
    }
    return container;
  }
  window.StudyUIRich = Object.freeze({render, copyText, source: element => element?.markdownSource ?? ''});
})();
