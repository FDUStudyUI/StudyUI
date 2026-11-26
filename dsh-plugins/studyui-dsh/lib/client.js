window.__ModuleLoader__.load({
  id: `studyui-dsh`,
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: `Module` });
    const react = require('react');
    const h = react.createElement;
    const TITLE = 'StudyUI';
    const CANVAS_PANEL_ID = 'studyui-canvas';
    const MATERIALS_PANEL_ID = 'studyui-materials';

    const Mark = ({ size = 20 }) =>
      h(
        'svg',
        { width: size, height: size, viewBox: '0 0 64 64', role: 'img', 'aria-label': TITLE },
        h('rect', { width: 64, height: 64, rx: 14, fill: '#29476f' }),
        h(
          'text',
          {
            x: 32,
            y: 44,
            textAnchor: 'middle',
            fontFamily: 'Georgia,serif',
            fontSize: 38,
            fontWeight: 700,
            fill: '#ffffff',
          },
          'S',
        ),
      );
    const Name = () => h('span', { style: { fontWeight: 700, letterSpacing: '0.01em' } }, TITLE);
    const CanvasIcon = () =>
      h(
        'svg',
        {
          width: 16,
          height: 16,
          viewBox: '0 0 24 24',
          fill: 'none',
          stroke: 'currentColor',
          strokeWidth: 1.8,
          strokeLinecap: 'round',
          strokeLinejoin: 'round',
          'aria-hidden': 'true',
        },
        h('rect', { x: 3, y: 3, width: 7, height: 7, rx: 1.5 }),
        h('rect', { x: 14, y: 3, width: 7, height: 7, rx: 1.5 }),
        h('rect', { x: 8.5, y: 14, width: 7, height: 7, rx: 1.5 }),
        h('path', { d: 'M6.5 10v2h11v-2M12 12v2' }),
      );
    const MaterialsIcon = () =>
      h(
        'svg',
        {
          width: 16,
          height: 16,
          viewBox: '0 0 24 24',
          fill: 'none',
          stroke: 'currentColor',
          strokeWidth: 1.8,
          strokeLinecap: 'round',
          strokeLinejoin: 'round',
          'aria-hidden': 'true',
        },
        h('path', { d: 'M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4A2 2 0 0 0 19 18l-5-9V3' }),
        h('path', { d: 'M7.5 14h9' }),
      );

    const guard = () => {
      if (document.title !== TITLE) document.title = TITLE;
    };

    const inject = [`slots`, `sessions`, `uiSession`];

    function apply(ctx) {
      const notifyCanvas = (frame, text) => {
        try {
          frame?.contentWindow?.postMessage({ type: 'studyui-run-status', text }, location.origin);
        } catch (_) {
          /* the canvas may have navigated away */
        }
      };

      const currentSessionId = () => {
        try {
          const current = ctx.uiSession?.adapter?.current?.value?.key;
          if (current) return current;
        } catch (_) {
          /* fall through to the session list */
        }
        try {
          const byId = ctx.sessions.list.getSnapshot().byId || {};
          const entries = Object.values(byId).sort((left, right) =>
            String(right.updatedAt || right.createdAt || '').localeCompare(
              String(left.updatedAt || left.createdAt || ''),
            ),
          );
          return entries[0]?.id;
        } catch (_) {
          return undefined;
        }
      };

      const sendPrompt = async (text, frame) => {
        if (!text || typeof text !== 'string') {
          return { ok: false, message: '提示词为空' };
        }
        const sessionId = currentSessionId();
        if (!sessionId) {
          const message = '请先创建一个 DSH 会话，然后再执行。';
          notifyCanvas(frame, message);
          return { ok: false, message };
        }
        let face;
        try {
          const scope = ctx.sessions.scope(sessionId);
          face = scope ? ctx.sessions.sessionOf(scope) : undefined;
        } catch (_) {
          face = undefined;
        }
        if (!face) {
          const message = '当前 DSH 会话尚未就绪，请打开该会话后再试。';
          notifyCanvas(frame, message);
          return { ok: false, message };
        }
        const message = '已发送到 DSH 会话，请在对话中确认审批并查看结果。';
        notifyCanvas(frame, message);
        try {
          const result = await face.prompt([{ type: 'text', text }], 'queue');
          if (result && result.ok === false) {
            const failed = '发送失败：' + (result.error?.message || '未知错误');
            notifyCanvas(frame, failed);
            return { ok: false, message: failed };
          }
          return { ok: true, message };
        } catch (error) {
          const failed = '发送失败：' + (error?.message || String(error));
          notifyCanvas(frame, failed);
          return { ok: false, message: failed };
        }
      };

      const runWorkflow = (flowId, frame, name) => {
        const label = name ? `「${name}」` : `（ID：${flowId}）`;
        return sendPrompt(`请运行我的工作流${label}，完成后把结果和产物告诉我。`, frame);
      };

      const CanvasPanel = ({ runWorkflow: run }) => {
        const frame = react.useRef(null);
        const [flows, setFlows] = react.useState([]);
        const [projects, setProjects] = react.useState([]);
        const [jobs, setJobs] = react.useState([]);
        const [selected, setSelected] = react.useState('');
        const [status, setStatus] = react.useState('');
        const [error, setError] = react.useState('');
        const [loading, setLoading] = react.useState(true);
        const [creating, setCreating] = react.useState(false);
        const [copying, setCopying] = react.useState('');
        const [directBusy, setDirectBusy] = react.useState(false);
        const [ready, setReady] = react.useState(false);
        const [loadError, setLoadError] = react.useState('');
        const [showDetails, setShowDetails] = react.useState(false);
        const dshDark = () => {
          if (document.body?.hasAttribute('data-ds-dark-theme')) return true;
          const source = document.documentElement.dataset.dsThemeSource;
          if (source === 'dark') return true;
          if (source === 'light') return false;
          return window.matchMedia('(prefers-color-scheme: dark)').matches;
        };
        const [dark, setDark] = react.useState(dshDark);
        const postTheme = (value) => {
          const win = frame.current?.contentWindow;
          if (win) win.postMessage({ type: 'studyui-canvas-theme', dark: value }, location.origin);
        };
        react.useEffect(() => {
          const sync = () => {
            const next = dshDark();
            setDark(next);
            postTheme(next);
          };
          const observer = new MutationObserver(sync);
          observer.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ['data-ds-theme-source', 'class', 'style'],
          });
          observer.observe(document.body, {
            attributes: true,
            attributeFilter: ['data-ds-dark-theme', 'class', 'style'],
          });
          const media = window.matchMedia('(prefers-color-scheme: dark)');
          media.addEventListener('change', sync);
          const timer = setInterval(sync, 1000);
          sync();
          return () => {
            observer.disconnect();
            media.removeEventListener('change', sync);
            clearInterval(timer);
          };
        }, []);
        const loadTimer = react.useRef(null);
        const jobLabels = {
          queued: '排队中',
          running: '运行中',
          completed: '已完成',
          failed: '失败',
          cancelled: '已取消',
        };
        const beginLoad = () => {
          setReady(false);
          setLoadError('');
          if (loadTimer.current) clearTimeout(loadTimer.current);
          loadTimer.current = setTimeout(() => setLoadError('加载超时，请重新加载。'), 20000);
        };
        const markReady = () => {
          setReady(true);
          setLoadError('');
          postTheme(dshDark());
          if (loadTimer.current) {
            clearTimeout(loadTimer.current);
            loadTimer.current = null;
          }
        };
        react.useEffect(
          () => () => {
            if (loadTimer.current) clearTimeout(loadTimer.current);
          },
          [],
        );
        const load = () => {
          setLoading(true);
          setError('');
          Promise.all([
            fetch('/studyui/canvas/api/v1/flows/', { headers: { accept: 'application/json' } }).then(
              (response) =>
                response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)),
            ),
            fetch('/studyui/canvas/api/v1/projects/', { headers: { accept: 'application/json' } }).then(
              (response) =>
                response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)),
            ),
          ])
            .then(([flowData, projectData]) => {
              const flowList = Array.isArray(flowData) ? flowData : flowData.flows || [];
              setFlows(flowList.filter((flow) => !flow.is_component));
              setProjects(Array.isArray(projectData) ? projectData : projectData.projects || []);
            })
            .catch((failure) => setError(String(failure?.message || failure)))
            .finally(() => setLoading(false));
        };
        const fetchJobs = () => {
          fetch('/studyui/api/workflows/jobs', { headers: { accept: 'application/json' } })
            .then((response) =>
              response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)),
            )
            .then((data) => setJobs(data.jobs || []))
            .catch(() => {
              /* the queue is best-effort in the panel */
            });
        };
        react.useEffect(load, []);
        react.useEffect(() => {
          fetchJobs();
          const timer = setInterval(fetchJobs, 3000);
          return () => clearInterval(timer);
        }, []);
        react.useEffect(() => {
          const onMessage = (event) => {
            if (event.origin !== location.origin) return;
            const data = event.data;
            if (!data) return;
            if (data.type === 'studyui-canvas-ready') {
              markReady();
              return;
            }
            if (data.type === 'studyui-run-workflow' && typeof data.flowId === 'string') {
              void run(data.flowId, null).then((result) => setStatus(result?.message || ''));
            }
          };
          window.addEventListener('message', onMessage);
          return () => window.removeEventListener('message', onMessage);
        }, [run]);
        const projectName = (id) => projects.find((project) => project.id === id)?.name || '未分组';
        const selectedFlow = flows.find((flow) => flow.id === selected);
        const currentJob = jobs.find((job) => job.flow_id === selected);
        const formatTime = (value) => {
          if (!value) return '';
          try {
            return new Date(value * 1000).toLocaleTimeString([], {
              hour: '2-digit',
              minute: '2-digit',
            });
          } catch (_) {
            return '';
          }
        };
        const openFlow = (flowId) => {
          setSelected(flowId);
          setStatus('');
          beginLoad();
        };
        const reload = () => {
          if (!selected) return;
          beginLoad();
          if (frame.current)
            frame.current.src = `/studyui/canvas/flow/${selected}?studyui_host=dsh&reload=${Date.now()}`;
        };
        const onFrameLoad = () => {
          const check = () => {
            try {
              if (frame.current?.contentDocument?.querySelector('.react-flow')) markReady();
            } catch (_) {
              /* the frame is cross-document while loading */
            }
          };
          setTimeout(check, 1200);
          setTimeout(check, 3500);
        };
        const createFlow = () => {
          if (creating) return;
          setCreating(true);
          setError('');
          const folderId = projects[0]?.id || null;
          fetch('/studyui/canvas/api/v1/flows/', {
            method: 'POST',
            headers: { 'content-type': 'application/json', accept: 'application/json' },
            body: JSON.stringify({
              name: '新建工作流',
              description: '',
              data: { nodes: [], edges: [] },
              is_component: false,
              folder_id: folderId,
            }),
          })
            .then((response) =>
              response.ok
                ? response.json()
                : response
                    .text()
                    .then((text) => Promise.reject(new Error(text || `HTTP ${response.status}`))),
            )
            .then((flow) => {
              setFlows((previous) => [flow, ...previous]);
              openFlow(flow.id);
            })
            .catch((failure) => setError(String(failure?.message || failure)))
            .finally(() => setCreating(false));
        };
        const copyFlow = async (flow) => {
          if (copying) return;
          setCopying(flow.id);
          setError('');
          try {
            const created = await fetch(`/studyui/canvas/api/v1/flows/${flow.id}/copy`, {
              method: 'POST',
              headers: { 'content-type': 'application/json', accept: 'application/json' },
              body: JSON.stringify({ name: `${flow.name || '工作流'} 副本` }),
            });
            if (!created.ok) throw new Error((await created.text()) || `HTTP ${created.status}`);
            const newFlow = await created.json();
            setFlows((previous) => [newFlow, ...previous]);
            openFlow(newFlow.id);
          } catch (failure) {
            setError(`复制失败：${failure?.message || failure}`);
          } finally {
            setCopying('');
          }
        };
        const runSelectedAgent = async () => {
          if (!selected) return;
          const result = await run(selected, null, selectedFlow?.name);
          setStatus(result?.message || '');
        };
        const startDirectRun = async () => {
          if (!selected || directBusy) return;
          setDirectBusy(true);
          setStatus('');
          setShowDetails(false);
          try {
            const response = await fetch(`/studyui/api/workflows/${selected}/run`, {
              method: 'POST',
              headers: { 'content-type': 'application/json', accept: 'application/json' },
              body: JSON.stringify({
                name: selectedFlow?.name || '',
                external_data_approved: true,
              }),
            });
            const data = await response.json().catch(() => null);
            if (!response.ok) {
              throw new Error(data?.detail || data?.error || `HTTP ${response.status}`);
            }
            setStatus(`已加入运行队列（${jobLabels[data.status] || data.status}）`);
            fetchJobs();
          } catch (failure) {
            setStatus(`直接运行失败：${failure?.message || failure}`);
          } finally {
            setDirectBusy(false);
          }
        };
        const cancelJob = (jobId) => {
          fetch(`/studyui/api/workflows/jobs/${jobId}/cancel`, { method: 'POST' })
            .then(() => fetchJobs())
            .catch(() => {});
        };
        const colors = dark
          ? {
              bg: '#151517',
              surface: '#1c1c1f',
              surfaceAlt: '#232326',
              text: '#f9fafb',
              muted: '#adb2b8',
              muted2: '#8b9098',
              border: '#2a2a2e',
              primary: '#4f6f9f',
              primaryText: '#ffffff',
              accent: '#9db7dd',
              okBg: '#182231',
              okText: '#b9cdea',
              errBg: '#2a1a1a',
              errText: '#f0a8a0',
            }
          : {
              bg: '#ffffff',
              surface: '#ffffff',
              surfaceAlt: '#f9fafb',
              text: '#0f1115',
              muted: '#81858c',
              muted2: '#61666b',
              border: '#e5e7eb',
              primary: '#29476f',
              primaryText: '#ffffff',
              accent: '#29476f',
              okBg: '#f2f6fb',
              okText: '#29476f',
              errBg: '#fdf3f2',
              errText: '#a33',
            };
        const pageStyle = {
          padding: '24px 28px',
          overflow: 'auto',
          height: '100%',
          background: colors.bg,
          color: colors.text,
          fontFamily: 'system-ui, sans-serif',
        };
        const headerRow = {
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: '16px',
          marginBottom: '18px',
        };
        const primaryButton = {
          border: `1px solid ${colors.primary}`,
          borderRadius: '8px',
          padding: '6px 12px',
          background: colors.primary,
          color: colors.primaryText,
          cursor: 'pointer',
          fontSize: '12px',
        };
        const ghostButton = {
          border: `1px solid ${colors.border}`,
          borderRadius: '8px',
          padding: '5px 10px',
          background: colors.surfaceAlt,
          color: colors.text,
          cursor: 'pointer',
          fontSize: '12px',
        };
        const flowRow = {
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '14px',
          padding: '12px 14px',
          border: `1px solid ${colors.border}`,
          borderRadius: '12px',
          background: colors.bg,
          marginBottom: '8px',
        };
        const flowList = [...flows].sort(
          (left, right) =>
            projectName(left.folder_id).localeCompare(projectName(right.folder_id)) ||
            String(left.name || '').localeCompare(String(right.name || '')),
        );
        const editorHeader = {
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          padding: '6px 12px',
          borderBottom: `1px solid ${colors.border}`,
          background: colors.bg,
          color: colors.text,
          fontFamily: 'system-ui, sans-serif',
          flex: '0 0 auto',
        };
        const mutedText = { fontSize: '12px', color: colors.muted };
        const jobText = { fontSize: '12px', color: colors.accent };
        const jobRow = {
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '12px',
          padding: '8px 12px',
          border: `1px solid ${colors.border}`,
          borderRadius: '10px',
          background: colors.bg,
          marginBottom: '6px',
        };
        const terminal = currentJob && ['completed', 'failed', 'cancelled'].includes(currentJob.status);
        const outputItems =
          currentJob?.result && Array.isArray(currentJob.result.outputs) ? currentJob.result.outputs : [];
        const outputNames = outputItems
          .map((item) => item?.component_display_name || item?.component_id)
          .filter(Boolean);
        if (selected) {
          return h(
            'div',
            {
              style: {
                display: 'flex',
                flexDirection: 'column',
                height: '100%',
                background: colors.bg,
              },
            },
            h(
              'div',
              { style: editorHeader },
              h('button', { type: 'button', style: ghostButton, onClick: () => setSelected('') }, '← 工作流'),
              h(
                'div',
                { style: { display: 'flex', flexDirection: 'column', minWidth: 0 } },
                h(
                  'span',
                  {
                    style: {
                      fontSize: '13px',
                      fontWeight: 600,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    },
                  },
                  selectedFlow?.name || '工作流',
                ),
                h(
                  'span',
                  { style: { fontSize: '11px', color: colors.muted } },
                  projectName(selectedFlow?.folder_id),
                ),
              ),
              h('div', { style: { flex: '1 1 auto' } }),
              !ready && !loadError ? h('span', { style: mutedText }, '正在加载…') : null,
              loadError ? h('span', { style: { fontSize: '12px', color: colors.errText } }, loadError) : null,
              loadError
                ? h('button', { type: 'button', style: ghostButton, onClick: reload }, '重新加载')
                : null,
              currentJob
                ? h(
                    'span',
                    { style: jobText },
                    `${jobLabels[currentJob.status] || currentJob.status}${
                      currentJob.error ? ' · ' + currentJob.error : ''
                    }`,
                  )
                : status
                  ? h('span', { style: jobText }, status)
                  : null,
              h(
                'button',
                {
                  type: 'button',
                  style: { ...primaryButton, opacity: ready && !directBusy ? 1 : 0.5 },
                  disabled: !ready || directBusy,
                  onClick: () => void startDirectRun(),
                },
                directBusy ? '提交中…' : '直接运行',
              ),
              h(
                'button',
                { type: 'button', style: ghostButton, onClick: () => void runSelectedAgent() },
                '交给 Agent',
              ),
            ),
            terminal
              ? h(
                  'div',
                  {
                    style: {
                      padding: '6px 12px',
                      borderBottom: `1px solid ${colors.border}`,
                      background: currentJob.status === 'completed' ? colors.okBg : colors.errBg,
                      color: currentJob.status === 'completed' ? colors.okText : colors.errText,
                      fontSize: '11.5px',
                    },
                  },
                  h(
                    'div',
                    { style: { display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' } },
                    h('strong', null, currentJob.status === 'completed' ? '直接运行完成' : '直接运行未完成'),
                    currentJob.error ? h('span', null, currentJob.error) : null,
                    outputNames.length ? h('span', null, `输出：${outputNames.join('、')}`) : null,
                    currentJob.result
                      ? h(
                          'button',
                          {
                            type: 'button',
                            style: { ...ghostButton, padding: '2px 7px', fontSize: '10.5px' },
                            onClick: () => setShowDetails((value) => !value),
                          },
                          showDetails ? '收起详情' : '查看详情',
                        )
                      : null,
                  ),
                  showDetails && currentJob.result
                    ? h(
                        'pre',
                        {
                          style: {
                            margin: '4px 0 0',
                            maxHeight: '120px',
                            overflow: 'auto',
                            whiteSpace: 'pre-wrap',
                            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                            fontSize: '10.5px',
                          },
                        },
                        JSON.stringify(currentJob.result, null, 2).slice(0, 8000),
                      )
                    : null,
                )
              : null,
            h(
              'div',
              { style: { flex: '1 1 auto', minHeight: 0 } },
              h('iframe', {
                ref: frame,
                src: `/studyui/canvas/flow/${selected}?studyui_host=dsh`,
                title: '工作流画布',
                onLoad: onFrameLoad,
                style: { border: 0, width: '100%', height: '100%', display: 'block' },
              }),
            ),
          );
        }
        return h(
          'div',
          { style: pageStyle },
          h(
            'div',
            { style: headerRow },
            h(
              'div',
              null,
              h('h2', { style: { margin: '0 0 6px', fontSize: '20px' } }, '工作流'),
              h(
                'p',
                { style: { margin: 0, color: colors.muted2, fontSize: '13px' } },
                '复制示例为模板后修改，或新建空白工作流；直接运行不消耗模型。',
              ),
            ),
            h(
              'div',
              { style: { display: 'flex', gap: '8px', flex: '0 0 auto' } },
              h('button', { type: 'button', style: ghostButton, onClick: load }, '刷新'),
              h(
                'button',
                { type: 'button', style: primaryButton, onClick: createFlow, disabled: creating },
                creating ? '创建中…' : '新建工作流',
              ),
            ),
          ),
          error ? h('p', { style: { color: colors.errText, fontSize: '12px' } }, error) : null,
          loading && flowList.length === 0
            ? h('p', { style: { color: colors.muted, fontSize: '13px' } }, '正在加载工作流…')
            : null,
          !loading && flowList.length === 0 && !error
            ? h(
                'p',
                { style: { color: colors.muted, fontSize: '13px' } },
                '还没有工作流，点击“新建工作流”开始。',
              )
            : null,
          flowList.map((flow) =>
            h(
              'div',
              { key: flow.id, style: flowRow },
              h(
                'div',
                { style: { display: 'flex', flexDirection: 'column', minWidth: 0 } },
                h(
                  'strong',
                  {
                    style: {
                      fontSize: '14px',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    },
                  },
                  flow.name || '未命名工作流',
                ),
                h(
                  'span',
                  { style: { fontSize: '12px', color: colors.muted, marginTop: '2px' } },
                  `${projectName(flow.folder_id)}${
                    flow.updated_at ? ' · ' + flow.updated_at.slice(0, 16).replace('T', ' ') : ''
                  }`,
                ),
              ),
              h(
                'div',
                { style: { display: 'flex', gap: '6px', flex: '0 0 auto' } },
                h(
                  'button',
                  {
                    type: 'button',
                    style: ghostButton,
                    disabled: copying === flow.id,
                    onClick: () => void copyFlow(flow),
                  },
                  copying === flow.id ? '复制中…' : '复制',
                ),
                h('button', { type: 'button', style: ghostButton, onClick: () => openFlow(flow.id) }, '打开'),
              ),
            ),
          ),
          h(
            'div',
            {
              style: {
                display: 'flex',
                alignItems: 'baseline',
                justifyContent: 'space-between',
                gap: '12px',
                margin: '20px 0 8px',
              },
            },
            h('h3', { style: { margin: 0, fontSize: '14px', fontWeight: 600 } }, '运行记录'),
            h('span', { style: { fontSize: '11px', color: colors.muted } }, '直接运行 · 不消耗模型'),
          ),
          jobs.length === 0
            ? h('p', { style: { margin: 0, color: colors.muted, fontSize: '12px' } }, '暂无直接运行记录。')
            : jobs.slice(0, 10).map((job) =>
                h(
                  'div',
                  { key: job.id, style: jobRow },
                  h(
                    'div',
                    { style: { display: 'flex', flexDirection: 'column', minWidth: 0 } },
                    h(
                      'strong',
                      {
                        style: {
                          fontSize: '12.5px',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        },
                      },
                      job.name || job.flow_id,
                    ),
                    h(
                      'span',
                      { style: { fontSize: '11px', color: colors.muted } },
                      `${jobLabels[job.status] || job.status}${
                        job.created_at ? ' · ' + formatTime(job.created_at) : ''
                      }${job.error ? ' · ' + job.error : ''}`,
                    ),
                  ),
                  ['queued', 'running'].includes(job.status)
                    ? h(
                        'button',
                        { type: 'button', style: ghostButton, onClick: () => cancelJob(job.id) },
                        '取消',
                      )
                    : h(
                        'button',
                        { type: 'button', style: ghostButton, onClick: () => openFlow(job.flow_id) },
                        '打开',
                      ),
                ),
              ),
        );
      };

      const panelStyle = {
        padding: '24px 28px',
        overflow: 'auto',
        height: '100%',
        background: '#ffffff',
        color: '#0f1115',
        fontFamily: 'system-ui, sans-serif',
      };
      const MaterialsPanel = ({ sendPrompt: send }) => {
        const [tasks, setTasks] = react.useState([]);
        const [datasets, setDatasets] = react.useState([]);
        const [error, setError] = react.useState('');
        const [status, setStatus] = react.useState(null);
        const [busy, setBusy] = react.useState('');
        react.useEffect(() => {
          let alive = true;
          fetch('/studyui/api/material-tasks', { headers: { accept: 'application/json' } })
            .then((response) =>
              response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)),
            )
            .then((data) => {
              if (alive) setTasks(data.tasks || []);
            })
            .catch((failure) => {
              if (alive) setError(String(failure?.message || failure));
            });
          fetch('/studyui/api/demo-datasets', { headers: { accept: 'application/json' } })
            .then((response) =>
              response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)),
            )
            .then((data) => {
              if (alive) setDatasets(data.datasets || []);
            })
            .catch(() => {
              /* the dataset row is optional */
            });
          return () => {
            alive = false;
          };
        }, []);
        const handoff = async (task, card) => {
          if (busy) return;
          setBusy(card.id);
          const result = await send(
            `我想做材料任务「${task.title} / ${card.title}」。目标是：${card.objective}。` +
              '需要哪些数据或参数请先告诉我，准备好后帮我完成分析。',
          );
          setStatus({ text: result?.message || '', ok: result?.ok !== false });
          setBusy('');
        };
        const handoffDataset = async (dataset) => {
          if (busy) return;
          setBusy(dataset.id);
          const request = (dataset.prompt || '帮我分析这份示例数据。')
            .replace(/（(?:文件：)?\{path\}）\s*$/, '')
            .replaceAll('{path}', '示例库中的文件')
            .trim();
          const result = await send(`「${dataset.title}」示例数据：${request}`);
          setStatus({ text: result?.message || '', ok: result?.ok !== false });
          setBusy('');
        };
        const taskCount = tasks.reduce((sum, task) => sum + (task.cards || []).length, 0);
        const container = { maxWidth: '1320px', margin: '0 auto' };
        const headerRow = {
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          gap: '16px',
          flexWrap: 'wrap',
          marginBottom: '14px',
        };
        const titleStyle = { margin: 0, fontSize: '22px', lineHeight: 1.2 };
        const subtitleStyle = {
          margin: '5px 0 0',
          color: '#61666b',
          fontSize: '12.5px',
          lineHeight: 1.5,
          maxWidth: '780px',
        };
        const statsRow = { display: 'flex', gap: '6px', flexWrap: 'wrap' };
        const pill = {
          border: '1px solid #e5e7eb',
          background: '#f9fafb',
          color: '#61666b',
          borderRadius: '999px',
          padding: '3px 9px',
          fontSize: '11px',
          whiteSpace: 'nowrap',
        };
        const statusBanner = {
          marginBottom: '12px',
          border: '1px solid #dbe4f0',
          background: '#f2f6fb',
          color: '#29476f',
          borderRadius: '8px',
          padding: '7px 10px',
          fontSize: '12px',
        };
        const errorBanner = {
          marginBottom: '12px',
          border: '1px solid #f3d6d2',
          background: '#fdf3f2',
          color: '#a33',
          borderRadius: '8px',
          padding: '7px 10px',
          fontSize: '12px',
        };
        const groupGrid = {
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
          gap: '12px',
          alignItems: 'start',
        };
        const groupCard = {
          border: '1px solid #e5e7eb',
          borderRadius: '12px',
          background: '#ffffff',
          overflow: 'hidden',
        };
        const groupHeader = {
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '8px',
          padding: '9px 12px',
          background: '#f9fafb',
          borderBottom: '1px solid #e5e7eb',
        };
        const groupTitle = {
          fontSize: '13px',
          fontWeight: 600,
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        };
        const groupMeta = { fontSize: '10.5px', color: '#81858c' };
        const itemHead = {
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '8px',
        };
        const itemTitle = {
          fontSize: '12.5px',
          fontWeight: 600,
          lineHeight: 1.35,
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        };
        const runButton = {
          border: '1px solid #dbe4f0',
          borderRadius: '6px',
          background: '#f6f8fc',
          color: '#29476f',
          cursor: 'pointer',
          fontSize: '10.5px',
          padding: '3px 7px',
          whiteSpace: 'nowrap',
        };
        const objectiveStyle = {
          fontSize: '11px',
          color: '#61666b',
          lineHeight: 1.45,
          marginTop: '3px',
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
        };
        const operationStyle = {
          fontSize: '10px',
          color: '#adb2b8',
          marginTop: '2px',
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
        };
        const sectionHeader = {
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          gap: '12px',
          margin: '18px 0 8px',
        };
        const sectionTitle = { margin: 0, fontSize: '14px', fontWeight: 600 };
        const datasetGrid = {
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '10px',
        };
        const datasetCard = {
          border: '1px solid #e5e7eb',
          borderRadius: '10px',
          background: '#ffffff',
          padding: '10px 11px',
          display: 'flex',
          flexDirection: 'column',
          gap: '3px',
        };
        const datasetTitle = { fontSize: '12px', fontWeight: 600, lineHeight: 1.35 };
        const datasetDesc = {
          fontSize: '10.5px',
          color: '#61666b',
          lineHeight: 1.45,
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
        };
        const datasetMeta = { fontSize: '10px', color: '#adb2b8' };
        const footerNote = { margin: '16px 0 0', fontSize: '11px', color: '#adb2b8' };
        const emptyText = { color: '#81858c', fontSize: '12px' };
        return h(
          'div',
          { style: panelStyle },
          h(
            'div',
            { style: container },
            h(
              'div',
              { style: headerRow },
              h(
                'div',
                null,
                h('h2', { style: titleStyle }, '材料任务'),
                h(
                  'p',
                  { style: subtitleStyle },
                  '确定性材料分析任务与五个示例数据集；点击后交给当前 DSH 会话，由 Agent 补齐输入并调用 MCP 执行。',
                ),
              ),
              h(
                'div',
                { style: statsRow },
                h('span', { style: pill }, `${tasks.length} 个任务组`),
                h('span', { style: pill }, `${taskCount} 个检查项`),
                h('span', { style: pill }, `${datasets.length} 个示例数据`),
                h(
                  'a',
                  {
                    href: '/studyui/workbench',
                    target: '_blank',
                    rel: 'noopener',
                    style: runButton,
                  },
                  '参数表单与运行记录 ↗',
                ),
              ),
            ),
            error ? h('div', { style: errorBanner }, `加载失败：${error}`) : null,
            status && status.text
              ? h('div', { style: status.ok ? statusBanner : errorBanner }, status.text)
              : null,
            tasks.length === 0 && !error ? h('p', { style: emptyText }, '正在加载任务卡…') : null,
            h(
              'div',
              { style: groupGrid },
              tasks.map((task) =>
                h(
                  'section',
                  { key: task.id, style: groupCard },
                  h(
                    'div',
                    { style: groupHeader },
                    h(
                      'div',
                      {
                        style: {
                          display: 'flex',
                          alignItems: 'baseline',
                          gap: '6px',
                          minWidth: 0,
                        },
                      },
                      h('span', { style: groupTitle }, task.title),
                      h('span', { style: groupMeta }, `v${task.version}`),
                    ),
                    h('span', { style: pill }, `${(task.cards || []).length} 项`),
                  ),
                  (task.cards || []).map((card, index) =>
                    h(
                      'div',
                      {
                        key: card.id,
                        title: card.conditions || '',
                        style: {
                          padding: '8px 12px',
                          borderTop: index ? '1px solid #f1f2f4' : 'none',
                        },
                      },
                      h(
                        'div',
                        { style: itemHead },
                        h('span', { style: itemTitle }, card.title),
                        h(
                          'button',
                          {
                            type: 'button',
                            disabled: Boolean(busy),
                            onClick: () => void handoff(task, card),
                            style: { ...runButton, opacity: busy ? 0.5 : 1 },
                          },
                          busy === card.id ? '发送中…' : '交给 DSH',
                        ),
                      ),
                      h('div', { style: objectiveStyle }, card.objective),
                      h('div', { style: operationStyle }, card.operation),
                    ),
                  ),
                ),
              ),
            ),
            h(
              'div',
              { style: sectionHeader },
              h('h3', { style: sectionTitle }, '示例数据 · 五案例'),
              h('span', { style: groupMeta }, '载入后由 Agent 分析'),
            ),
            h(
              'div',
              { style: datasetGrid },
              datasets.map((dataset) =>
                h(
                  'div',
                  { key: dataset.id, style: datasetCard },
                  h('div', { style: datasetTitle }, dataset.title),
                  h('div', { style: datasetDesc }, dataset.desc),
                  h('div', { style: datasetMeta }, `${dataset.format || ''} · ${dataset.row_count ?? ''} 行`),
                  h(
                    'button',
                    {
                      type: 'button',
                      disabled: Boolean(busy),
                      onClick: () => void handoffDataset(dataset),
                      style: { ...runButton, marginTop: '4px', alignSelf: 'flex-start' },
                    },
                    busy === dataset.id ? '发送中…' : '载入并分析',
                  ),
                ),
              ),
            ),
            h(
              'p',
              { style: footerNote },
              '点击任务或示例后，Agent 会在当前 DSH 会话中补齐输入、调用 MCP 工具并返回结果。',
            ),
          ),
        );
      };

      ctx.slots.inject(`sidebar.brand.mark`, () =>
        ctx.slots.register({ name: `sidebar.brand.mark`, id: `studyui-brand-mark` }, Mark),
      );
      ctx.slots.inject(`sidebar.brand.name`, () =>
        ctx.slots.register({ name: `sidebar.brand.name`, id: `studyui-brand-name` }, Name),
      );
      ctx.slots.inject(`sidebar.panellist`, () =>
        ctx.slots.register(
          { name: `sidebar.panellist`, id: CANVAS_PANEL_ID, order: 5, label: `工作流画布` },
          CanvasIcon,
        ),
      );
      ctx.slots.inject(`sidebar.panellist`, () =>
        ctx.slots.register(
          { name: `sidebar.panellist`, id: MATERIALS_PANEL_ID, order: 6, label: `材料任务` },
          MaterialsIcon,
        ),
      );
      ctx.slots.inject(`main`, () =>
        ctx.slots.register(
          { name: `main`, key: CANVAS_PANEL_ID, inject: () => ({ runWorkflow }) },
          CanvasPanel,
        ),
      );
      ctx.slots.inject(`main`, () =>
        ctx.slots.register(
          { name: `main`, key: MATERIALS_PANEL_ID, inject: () => ({ sendPrompt }) },
          MaterialsPanel,
        ),
      );

      const observer = new MutationObserver(guard);
      const start = () => {
        if (document.head) {
          observer.observe(document.head, { childList: true, subtree: true, characterData: true });
        }
        guard();
      };
      if (document.head) start();
      else document.addEventListener(`DOMContentLoaded`, start);
      setInterval(guard, 1000);
    }

    exports.apply = apply;
    exports.inject = inject;
    return module.exports;
  },
});
