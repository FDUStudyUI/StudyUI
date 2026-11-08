/* StudyUI Markdown rendering. Dependencies are shipped locally; no runtime CDN. */
(() => {
  'use strict';
  const MAX_SOURCE = 250000;
  const safeURL = (value) => {
    try {
      const url = new URL(value, location.href);
      return ['http:', 'https:', 'mailto:'].includes(url.protocol) ? url.href : null;
    } catch (_) {
      return null;
    }
  };
  const md = window.markdownit({ html: false, linkify: true, breaks: false, typographer: false });
  const escape = md.utils.escapeHtml;

  function mathHTML(source, display) {
    const cls = display ? 'math-block' : 'math-inline';
    try {
      const rendered = window.katex.renderToString(source, {
        displayMode: display,
        throwOnError: true,
        trust: false,
        strict: 'error',
        maxExpand: 500,
        maxSize: 20,
        output: 'htmlAndMathml',
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
    const pos = state.pos,
      source = state.src;
    let open,
      close,
      display = false;
    if (source.startsWith('\\(', pos)) {
      open = '\\(';
      close = '\\)';
    } else if (source.startsWith('\\[', pos)) {
      open = '\\[';
      close = '\\]';
      display = true;
    } else if (source.startsWith('$$', pos)) {
      open = '$$';
      close = '$$';
      display = true;
    } else if (source[pos] === '$' && !escapedAt(source, pos)) {
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
      token.meta = { display };
    }
    state.pos = end + close.length;
    return true;
  });
  md.renderer.rules.studyui_math = (tokens, index) =>
    mathHTML(tokens[index].content, tokens[index].meta.display);

  md.block.ruler.before(
    'fence',
    'studyui_math_block',
    (state, startLine, endLine, silent) => {
      const start = state.bMarks[startLine] + state.tShift[startLine];
      const first = state.src.slice(start, state.eMarks[startLine]);
      const open = first.startsWith('$$') ? '$$' : first.startsWith('\\[') ? '\\[' : null;
      if (!open || state.sCount[startLine] - state.blkIndent >= 4) return false;
      const close = open === '$$' ? '$$' : '\\]';
      let end = startLine,
        content = first.slice(open.length),
        closeAt = content.indexOf(close);
      while (closeAt < 0 && ++end < endLine) {
        content += '\n' + state.src.slice(state.bMarks[end] + state.tShift[end], state.eMarks[end]);
        closeAt = content.indexOf(close);
      }
      if (closeAt < 0 || content.slice(closeAt + close.length).trim()) return false;
      if (silent) return true;
      const token = state.push('studyui_math', '', 0);
      token.block = true;
      token.content = content.slice(0, closeAt).trim();
      token.meta = { display: true };
      token.map = [startLine, end + 1];
      state.line = end + 1;
      return true;
    },
    { alt: ['paragraph', 'reference', 'blockquote', 'list'] },
  );

  const linkOpen =
    md.renderer.rules.link_open ||
    ((tokens, index, options, env, self) => self.renderToken(tokens, index, options));
  md.renderer.rules.link_open = (tokens, index, options, env, self) => {
    const token = tokens[index],
      href = safeURL(token.attrGet('href') || '');
    if (!href) token.attrSet('href', '#');
    else token.attrSet('href', href);
    token.attrSet('target', '_blank');
    token.attrSet('rel', 'noopener noreferrer');
    if (href && /https:\/\/(?:doi\.org|arxiv\.org)\//.test(href)) token.attrSet('class', 'doi-badge');
    return linkOpen(tokens, index, options, env, self);
  };
  // Do not transmit a research session's reading behavior to arbitrary image hosts.
  md.renderer.rules.image = (tokens, index) => {
    const token = tokens[index],
      label = token.content || '图片',
      href = safeURL(token.attrGet('src') || '');
    return href
      ? `<a class="image-source-link" href="${escape(href)}" target="_blank" rel="noopener noreferrer">图片：${escape(label)}（打开原图）</a>`
      : `<span>图片：${escape(label)}</span>`;
  };

  async function copyText(text, button) {
    try {
      await navigator.clipboard.writeText(text);
      if (button) {
        const old = button.textContent;
        button.textContent = '已复制';
        setTimeout(() => {
          button.textContent = old;
        }, 1600);
      }
      if (typeof window.toast === 'function') window.toast('已复制原始文本');
      return true;
    } catch (_) {
      if (typeof window.toast === 'function') window.toast('复制失败，请选中文本后复制');
      return false;
    }
  }

  function render(raw, options = {}) {
    const source = String(raw ?? ''),
      container = document.createElement('div');
    container.className = 'rich-content';
    container.markdownSource = source;
    container.setAttribute('aria-busy', options.streaming ? 'true' : 'false');
    if (source.length > MAX_SOURCE) {
      const note = document.createElement('p');
      note.className = 'render-warning';
      note.textContent = '回答较长，显示纯文本；复制和导出仍保留完整原文。';
      const plain = document.createElement('pre');
      plain.className = 'rich-plain';
      plain.textContent = source;
      container.append(note, plain);
      return container;
    }
    container.innerHTML = window.DOMPurify.sanitize(md.render(source), {
      FORBID_TAGS: ['img', 'iframe', 'object', 'embed', 'style', 'script', 'form', 'input'],
      ADD_ATTR: ['target'],
    });
    for (const table of container.querySelectorAll('table')) {
      const wrap = document.createElement('div');
      wrap.className = 'rich-table-wrap';
      wrap.tabIndex = 0;
      wrap.setAttribute('role', 'region');
      wrap.setAttribute('aria-label', '数据表格，可横向滚动');
      table.classList.add('rich-table');
      table.replaceWith(wrap);
      wrap.append(table);
    }
    for (const pre of container.querySelectorAll('pre')) {
      const code = pre.querySelector('code');
      if (!code) continue;
      const language =
        Array.from(code.classList)
          .find((cls) => cls.startsWith('language-'))
          ?.slice(9) || 'text';
      const wrapper = document.createElement('div');
      wrapper.className = 'code-block';
      const head = document.createElement('div');
      head.className = 'code-header';
      const label = document.createElement('span');
      label.className = 'code-lang';
      label.textContent = language;
      const actions = document.createElement('div');
      actions.className = 'code-actions';
      const copy = document.createElement('button');
      copy.type = 'button';
      copy.className = 'code-btn';
      copy.textContent = '复制代码';
      copy.addEventListener('click', () => copyText(code.textContent, copy));
      actions.append(copy);
      if (!options.streaming && ['python', 'py'].includes(language.toLowerCase())) {
        const draft = document.createElement('button');
        draft.type = 'button';
        draft.className = 'code-btn';
        draft.textContent = '保存代码审核草稿';
        draft.addEventListener('click', () => window.insertCanvasNode?.(code.textContent, language));
        actions.append(draft);
      }
      head.append(label, actions);
      pre.replaceWith(wrapper);
      wrapper.append(head, pre);
    }
    return container;
  }

  function lineContinuation(block, nextLine) {
    const first = block.split(/\r?\n/).find((line) => line.trim() !== '') || '';
    const list = /^ {0,3}(?:[-+*]|\d+[.)])\s+/.test(first);
    const quote = /^ {0,3}>/.test(first);
    const indented = /^(?: {4,}|\t)/.test(first);
    const nextList = /^ {0,3}(?:[-+*]|\d+[.)])\s+/.test(nextLine);
    const nextQuote = /^ {0,3}>/.test(nextLine);
    const nextIndented = /^(?: {2,}|\t)/.test(nextLine);
    return (
      (list && (nextList || nextQuote || nextIndented)) ||
      (quote && (nextQuote || nextIndented)) ||
      (indented && nextIndented)
    );
  }

  function stableMarkdownBoundary(source) {
    let fence = null,
      mathFence = null,
      lastBoundary = 0,
      segmentStart = 0,
      lineStart = 0;
    while (lineStart < source.length) {
      const newline = source.indexOf('\n', lineStart);
      const lineEnd = newline < 0 ? source.length : newline + 1;
      const line = source.slice(lineStart, newline < 0 ? source.length : newline).replace(/\r$/, '');
      if (fence) {
        const close = line.match(/^ {0,3}(`{3,}|~{3,})[ \t]*$/);
        if (close && close[1][0] === fence.char && close[1].length >= fence.length) {
          fence = null;
          if (newline >= 0) {
            lastBoundary = lineEnd;
            segmentStart = lineEnd;
          }
        }
        lineStart = lineEnd;
        continue;
      }
      if (mathFence) {
        if (line.includes(mathFence)) {
          mathFence = null;
          if (newline >= 0) {
            lastBoundary = lineEnd;
            segmentStart = lineEnd;
          }
        }
        lineStart = lineEnd;
        continue;
      }
      const openFence = line.match(/^ {0,3}(`{3,}|~{3,})/);
      if (openFence) {
        const marker = openFence[1];
        const closing = new RegExp(`${marker[0]}{${marker.length},}`);
        if (!closing.test(line.slice(openFence[0].length)))
          fence = { char: marker[0], length: marker.length };
        lineStart = lineEnd;
        continue;
      }
      const trimmed = line.trimStart();
      const openMath = trimmed.startsWith('$$') ? '$$' : trimmed.startsWith('\\[') ? '\\]' : null;
      if (openMath) {
        const content = trimmed.slice(openMath === '$$' ? 2 : 2);
        if (!content.includes(openMath)) mathFence = openMath;
        else if (newline >= 0) {
          lastBoundary = lineEnd;
          segmentStart = lineEnd;
        }
        lineStart = lineEnd;
        continue;
      }
      if (line.trim() === '' && newline >= 0) {
        let nextStart = lineEnd;
        while (nextStart < source.length) {
          const nextEnd = source.indexOf('\n', nextStart);
          const next = source.slice(nextStart, nextEnd < 0 ? source.length : nextEnd).replace(/\r$/, '');
          if (next.trim() !== '') {
            if (!lineContinuation(source.slice(segmentStart, lineStart), next)) {
              lastBoundary = nextStart;
              segmentStart = nextStart;
            }
            break;
          }
          if (nextEnd < 0) break;
          nextStart = nextEnd + 1;
        }
      }
      lineStart = lineEnd;
    }
    return lastBoundary;
  }

  function nodeKey(node) {
    if (node.nodeType !== Node.ELEMENT_NODE) return null;
    if (node.classList.contains('dsh-stream-cursor')) return 'stream-cursor';
    return node.getAttribute('data-md-key') || node.id || null;
  }

  function sameNodeKind(left, right) {
    if (left === right) return true;
    if (left.nodeType !== right.nodeType) return false;
    return (
      left.nodeType !== Node.ELEMENT_NODE ||
      (left.namespaceURI === right.namespaceURI && left.tagName === right.tagName)
    );
  }

  function syncAttributes(current, next) {
    for (const attribute of Array.from(current.attributes)) {
      if (!next.hasAttribute(attribute.name) && !attribute.name.startsWith('data-stream-')) {
        current.removeAttribute(attribute.name);
      }
    }
    for (const attribute of Array.from(next.attributes)) {
      if (current.getAttribute(attribute.name) !== attribute.value) {
        current.setAttribute(attribute.name, attribute.value);
      }
    }
  }

  function reconcileChildren(current, next) {
    const oldChildren = Array.from(current.childNodes);
    const used = new Set();
    let insertionPoint = current.firstChild;
    for (const fresh of Array.from(next.childNodes)) {
      const key = nodeKey(fresh);
      let candidate =
        key === null ? null : oldChildren.find((child) => !used.has(child) && nodeKey(child) === key);
      if (!candidate && insertionPoint && !used.has(insertionPoint) && sameNodeKind(insertionPoint, fresh)) {
        candidate = insertionPoint;
      }
      if (!candidate) candidate = oldChildren.find((child) => !used.has(child) && sameNodeKind(child, fresh));
      let node = fresh;
      if (candidate) {
        used.add(candidate);
        node = reconcileNode(candidate, fresh);
        if (node !== candidate) {
          current.replaceChild(node, candidate);
          used.delete(candidate);
          used.add(node);
        }
      } else used.add(node);
      if (node !== insertionPoint) current.insertBefore(node, insertionPoint);
      insertionPoint = node.nextSibling;
    }
    for (const child of Array.from(current.childNodes)) {
      if (!used.has(child)) child.remove();
    }
  }

  function reconcileNode(current, next) {
    if (!sameNodeKind(current, next)) return next;
    if (current === next) return current;
    if (current.nodeType === Node.TEXT_NODE || current.nodeType === Node.COMMENT_NODE) {
      if (current.nodeValue !== next.nodeValue) current.nodeValue = next.nodeValue;
      return current;
    }
    syncAttributes(current, next);
    reconcileChildren(current, next);
    return current;
  }

  function createStream(host, options = {}) {
    let tailText = '';
    let tailNode = null;
    const cursor = document.createElement('span');
    cursor.className = 'dsh-stream-cursor';
    const renderTail = (text) => {
      const node = render(text, { ...options, streaming: true });
      node.classList.add('dsh-stream-tail');
      const inlineNodes = node.querySelectorAll('p, li, td, th');
      (inlineNodes[inlineNodes.length - 1] || node).append(cursor);
      return node;
    };
    const updateTail = () => {
      if (!tailText) {
        tailNode?.remove();
        tailNode = null;
        return;
      }
      const next = renderTail(tailText);
      if (tailNode) reconcileNode(tailNode, next);
      else {
        tailNode = next;
        host.append(next);
      }
    };
    return Object.freeze({
      append(chunk) {
        if (typeof chunk !== 'string' || !chunk) return;
        tailText += chunk;
        const boundary = stableMarkdownBoundary(tailText);
        if (boundary > 0) {
          const stable = render(tailText.slice(0, boundary), { ...options, streaming: false });
          stable.classList.add('dsh-stream-committed');
          const remainder = tailText.slice(boundary);
          if (tailNode) {
            reconcileNode(tailNode, stable);
            tailNode = null;
          } else host.append(stable);
          tailText = remainder;
          updateTail();
          return;
        }
        updateTail();
      },
      finish() {
        if (tailNode) {
          if (tailText) {
            const finalNode = render(tailText, { ...options, streaming: false });
            finalNode.classList.add('dsh-stream-committed');
            reconcileNode(tailNode, finalNode);
          } else tailNode.remove();
        } else if (tailText) host.append(render(tailText, { ...options, streaming: false }));
        tailNode = null;
        tailText = '';
      },
    });
  }

  window.StudyUIRich = Object.freeze({
    render,
    createStream,
    copyText,
    source: (element) => element?.markdownSource ?? '',
  });
})();
