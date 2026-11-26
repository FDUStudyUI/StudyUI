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

      const MATERIAL_PROJECT_KEY = 'studyui.material.project_id';
      const MATERIAL_SESSION_KEY = 'studyui.material.session_id';

      const parseJsonBody = async (response) => {
        const text = await response.text();
        let data = null;
        if (text) {
          try {
            data = JSON.parse(text);
          } catch (_) {
            data = text;
          }
        }
        if (!response.ok) {
          const message =
            data && typeof data === 'object'
              ? (data.detail ?? data.error ?? data.message ?? `HTTP ${response.status}`)
              : data || `HTTP ${response.status}`;
          throw new Error(typeof message === 'string' ? message : JSON.stringify(message));
        }
        return data;
      };

      const requestJson = (url, options = {}) =>
        fetch(url, {
          ...options,
          headers: { accept: 'application/json', ...(options.headers || {}) },
        }).then(parseJsonBody);

      const ensureMaterialSession = async () => {
        const load = async () => {
          let projectId = localStorage.getItem(MATERIAL_PROJECT_KEY) || '';
          let sessionId = localStorage.getItem(MATERIAL_SESSION_KEY) || '';
          const [projects, sessions] = await Promise.all([
            requestJson('/studyui/api/projects'),
            requestJson('/studyui/api/sessions'),
          ]);
          const projectList = Array.isArray(projects) ? projects : projects?.projects || [];
          const sessionList = Array.isArray(sessions) ? sessions : sessions?.sessions || [];
          if (sessionId) {
            const existing = sessionList.find((row) => row.id === sessionId);
            if (existing) {
              if (existing.project_id) {
                projectId = existing.project_id;
                localStorage.setItem(MATERIAL_PROJECT_KEY, projectId);
              }
              return sessionId;
            }
          }
          if (!projectId || !projectList.some((row) => row.id === projectId)) {
            const project = await requestJson('/studyui/api/projects', {
              method: 'POST',
              headers: { 'content-type': 'application/json' },
              body: JSON.stringify({ title: '材料分析', description: '材料任务与方法协议' }),
            });
            projectId = project.id;
            localStorage.setItem(MATERIAL_PROJECT_KEY, projectId);
          }
          const session = await requestJson('/studyui/api/sessions', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ title: '材料工作流', project_id: projectId, workspace_id: null }),
          });
          sessionId = session.id;
          localStorage.setItem(MATERIAL_SESSION_KEY, sessionId);
          return sessionId;
        };
        try {
          return await load();
        } catch (error) {
          localStorage.removeItem(MATERIAL_PROJECT_KEY);
          localStorage.removeItem(MATERIAL_SESSION_KEY);
          try {
            return await load();
          } catch (_) {
            throw error;
          }
        }
      };

      const MODAL_STYLE = {
        overlay: {
          position: 'fixed',
          inset: 0,
          zIndex: 1000,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '20px',
          background: 'rgba(15, 17, 21, 0.42)',
        },
        panel: {
          boxSizing: 'border-box',
          maxHeight: '90vh',
          overflow: 'auto',
          padding: '22px',
          border: '1px solid #e5e7eb',
          borderRadius: '16px',
          background: '#ffffff',
          color: '#0f1115',
          boxShadow: '0 18px 70px rgba(34, 37, 31, 0.3)',
          fontFamily: 'system-ui, sans-serif',
        },
        header: {
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: '12px',
          marginBottom: '14px',
        },
        title: { margin: '0 0 4px', fontSize: '18px', lineHeight: 1.25 },
        subtitle: { margin: 0, color: '#61666b', fontSize: '12px', lineHeight: 1.5 },
        closeButton: {
          flex: '0 0 auto',
          width: '28px',
          height: '28px',
          border: '1px solid #e5e7eb',
          borderRadius: '8px',
          background: '#f9fafb',
          color: '#61666b',
          cursor: 'pointer',
          fontSize: '16px',
          lineHeight: 1,
        },
        primaryButton: {
          border: '1px solid #29476f',
          borderRadius: '8px',
          padding: '7px 12px',
          background: '#29476f',
          color: '#ffffff',
          cursor: 'pointer',
          fontSize: '12px',
          fontWeight: 600,
        },
        ghostButton: {
          border: '1px solid #dbe4f0',
          borderRadius: '8px',
          padding: '6px 10px',
          background: '#f6f8fc',
          color: '#29476f',
          cursor: 'pointer',
          fontSize: '12px',
        },
        input: {
          boxSizing: 'border-box',
          width: '100%',
          border: '1px solid #d5d9e0',
          borderRadius: '8px',
          padding: '7px 9px',
          background: '#ffffff',
          color: '#0f1115',
          fontFamily: 'inherit',
          fontSize: '12px',
        },
        field: { display: 'flex', flexDirection: 'column', gap: '5px', minWidth: 0 },
        fieldLabel: { fontSize: '11.5px', color: '#61666b' },
        fieldHint: { fontSize: '10.5px', color: '#9aa0a8' },
        fieldGrid: {
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
          gap: '12px',
        },
        fieldset: {
          border: '1px solid #e5e7eb',
          borderRadius: '12px',
          padding: '12px',
          margin: '12px 0',
        },
        legend: { padding: '0 6px', fontSize: '12px', fontWeight: 600, color: '#384250' },
        sectionHeader: {
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          gap: '10px',
          margin: '18px 0 8px',
        },
        sectionTitle: { margin: 0, fontSize: '14px', fontWeight: 600 },
        note: { margin: 0, color: '#81858c', fontSize: '12px' },
        info: {
          margin: '0 0 12px',
          border: '1px solid #dbe4f0',
          borderRadius: '8px',
          background: '#f2f6fb',
          color: '#29476f',
          padding: '7px 10px',
          fontSize: '12px',
          lineHeight: 1.5,
        },
        error: {
          margin: '0 0 12px',
          border: '1px solid #f3d6d2',
          borderRadius: '8px',
          background: '#fdf3f2',
          color: '#a33',
          padding: '7px 10px',
          fontSize: '12px',
          lineHeight: 1.5,
        },
        card: {
          border: '1px solid #e5e7eb',
          borderRadius: '10px',
          background: '#ffffff',
          padding: '9px 11px',
          marginBottom: '6px',
          fontSize: '12px',
          lineHeight: 1.5,
        },
        muted: { color: '#81858c' },
        mono: { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace' },
      };

      const Modal = ({ title, subtitle, onClose, width = 920, children }) =>
        h(
          'div',
          {
            style: MODAL_STYLE.overlay,
            onMouseDown: (event) => {
              if (event.target === event.currentTarget) onClose();
            },
          },
          h(
            'div',
            {
              role: 'dialog',
              'aria-modal': 'true',
              'aria-label': title,
              style: { ...MODAL_STYLE.panel, width: `min(${width}px, 100%)` },
            },
            h(
              'div',
              { style: MODAL_STYLE.header },
              h(
                'div',
                null,
                h('h2', { style: MODAL_STYLE.title }, title),
                subtitle ? h('p', { style: MODAL_STYLE.subtitle }, subtitle) : null,
              ),
              h(
                'button',
                {
                  type: 'button',
                  style: MODAL_STYLE.closeButton,
                  onClick: onClose,
                  'aria-label': '关闭',
                },
                '×',
              ),
            ),
            children,
          ),
        );

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

      const MaterialTaskDialog = ({ open, onClose }) => {
        const [sessionId, setSessionId] = react.useState('');
        const [sessionState, setSessionState] = react.useState('idle');
        const [sessionLoading, setSessionLoading] = react.useState(false);
        const [task, setTask] = react.useState('mechanics');
        const [path, setPath] = react.useState('');
        const [filename, setFilename] = react.useState('');
        const [sheet, setSheet] = react.useState('');
        const [sheets, setSheets] = react.useState([]);
        const [header, setHeader] = react.useState('1');
        const [format, setFormat] = react.useState('auto');
        const [preview, setPreview] = react.useState(null);
        const [x, setX] = react.useState('');
        const [y, setY] = react.useState('');
        const [xUnit, setXUnit] = react.useState('');
        const [yUnit, setYUnit] = react.useState('');
        const [sort, setSort] = react.useState(false);
        const [fitMin, setFitMin] = react.useState('');
        const [fitMax, setFitMax] = react.useState('');
        const [offset, setOffset] = react.useState('');
        const [baseline, setBaseline] = react.useState('');
        const [prominence, setProminence] = react.useState('');
        const [checks, setChecks] = react.useState([]);
        const [guardReport, setGuardReport] = react.useState(null);
        const [checkedSpec, setCheckedSpec] = react.useState('');
        const [uploading, setUploading] = react.useState(false);
        const [previewing, setPreviewing] = react.useState(false);
        const [checking, setChecking] = react.useState(false);
        const [building, setBuilding] = react.useState(false);
        const [status, setStatus] = react.useState(null);
        const openedRef = react.useRef(false);
        const sessionIdRef = react.useRef('');

        const resetForm = () => {
          setTask('mechanics');
          setFormat('auto');
          setPath('');
          setFilename('');
          setSheet('');
          setSheets([]);
          setHeader('1');
          setPreview(null);
          setX('');
          setY('');
          setXUnit('');
          setYUnit('');
          setSort(false);
          setFitMin('');
          setFitMax('');
          setOffset('');
          setBaseline('');
          setProminence('');
          setChecks([]);
          setGuardReport(null);
          setCheckedSpec('');
        };

        react.useEffect(() => {
          if (!open) {
            openedRef.current = false;
            return undefined;
          }
          if (openedRef.current) return undefined;
          openedRef.current = true;
          let alive = true;
          setSessionLoading(true);
          setSessionState('loading');
          ensureMaterialSession()
            .then((id) => {
              if (!alive) return;
              const previous = sessionIdRef.current;
              const changed = Boolean(previous && previous !== id);
              if (changed) resetForm();
              sessionIdRef.current = id;
              setSessionId(id);
              setSessionState('ready');
              if (!path || changed) setStatus({ text: '请上传本项目的测量文件。', ok: true });
            })
            .catch((error) => {
              if (!alive) return;
              setSessionState('error');
              setStatus({ text: `材料会话准备失败：${error?.message || error}`, ok: false });
            })
            .finally(() => {
              if (alive) setSessionLoading(false);
            });
          return () => {
            alive = false;
          };
        }, [open]);

        react.useEffect(() => {
          if (!open) return undefined;
          const onKey = (event) => {
            if (event.key === 'Escape') onClose();
          };
          window.addEventListener('keydown', onKey);
          return () => window.removeEventListener('keydown', onKey);
        }, [open]);

        const invalidate = () => setCheckedSpec('');

        const change = (setter) => (event) => {
          setter(event.target.value);
          invalidate();
        };

        const buildSpec = () => {
          const importOptions = { header: Math.max(0, Number(header || '1') - 1) };
          if (sheet) importOptions.sheet = sheet;
          const spec = {
            task,
            path,
            x,
            y,
            x_unit: xUnit.trim(),
            y_unit: yUnit.trim(),
            import_options: importOptions,
            file_format: format,
            sort,
          };
          if (task === 'mechanics') {
            if (fitMin !== '' && fitMax !== '') spec.fit_range = [Number(fitMin), Number(fitMax)];
            if (offset !== '') spec.yield_offset = Number(offset);
          } else {
            if (baseline) spec.baseline = baseline;
            if (prominence !== '') spec.prominence = Number(prominence);
          }
          return spec;
        };

        const applyPreview = (data, previous) => {
          const columns = Array.isArray(data?.columns) ? data.columns : [];
          const sheetNames = Array.isArray(data?.sheets) ? data.sheets : [];
          setPreview(data);
          setSheets(sheetNames);
          setSheet(previous.sheet && sheetNames.includes(previous.sheet) ? previous.sheet : '');
          setX((current) => {
            const keep = previous.x || current;
            return columns.some((column) => column.name === keep) ? keep : columns[0]?.name || '';
          });
          setY((current) => {
            const keep = previous.y || current;
            return columns.some((column) => column.name === keep) ? keep : columns[1]?.name || '';
          });
        };

        const previewMaterial = async (overrides = {}) => {
          const targetPath = overrides.path ?? path;
          if (!targetPath || !sessionId) return;
          const headerValue = overrides.header ?? header;
          const formatValue = overrides.format ?? format;
          const sheetValue = overrides.sheet ?? sheet;
          setPreviewing(true);
          invalidate();
          setStatus({ text: '正在读取文件…', ok: true });
          try {
            const importOptions = { header: Math.max(0, Number(headerValue || '1') - 1) };
            if (sheetValue) importOptions.sheet = sheetValue;
            const data = await requestJson('/studyui/api/material-tasks/preview', {
              method: 'POST',
              headers: { 'content-type': 'application/json' },
              body: JSON.stringify({
                session_id: sessionId,
                path: targetPath,
                import_options: importOptions,
                file_format: formatValue,
              }),
            });
            applyPreview(data, { x, y, sheet: sheetValue });
            setStatus({ text: '选择列和实测单位，填写方法参数后检查。', ok: true });
          } catch (error) {
            setStatus({ text: `预览失败：${error?.message || error}`, ok: false });
          } finally {
            setPreviewing(false);
          }
        };

        const uploadFile = async (file) => {
          if (!file || !sessionId || uploading) return;
          setUploading(true);
          invalidate();
          setPreview(null);
          setSheets([]);
          setPath('');
          setFilename(file.name);
          setX('');
          setY('');
          setChecks([]);
          setGuardReport(null);
          setStatus({ text: '正在上传…', ok: true });
          try {
            const response = await fetch('/studyui/api/upload', {
              method: 'POST',
              headers: {
                'X-Filename': encodeURIComponent(file.name),
                'X-StudyUI-Session': sessionId,
              },
              body: file,
            });
            const data = await parseJsonBody(response);
            setPath(data.path);
            setSheet('');
            setHeader('1');
            await previewMaterial({ path: data.path, header: '1', sheet: '' });
          } catch (error) {
            setStatus({ text: `上传失败：${error?.message || error}`, ok: false });
          } finally {
            setUploading(false);
          }
        };

        const runCheck = async (event) => {
          event?.preventDefault?.();
          if (!sessionId) {
            setStatus({ text: '材料会话尚未就绪，请稍后重试。', ok: false });
            return;
          }
          if (!path) {
            setStatus({ text: '请先上传数据。', ok: false });
            return;
          }
          const spec = buildSpec();
          setChecking(true);
          setCheckedSpec('');
          setChecks([]);
          setGuardReport(null);
          setStatus({ text: '正在检查方法条件…', ok: true });
          try {
            const data = await requestJson('/studyui/api/material-tasks/check', {
              method: 'POST',
              headers: { 'content-type': 'application/json' },
              body: JSON.stringify({ session_id: sessionId, protocol: spec }),
            });
            const nextActions = Array.isArray(data?.next_actions) ? data.next_actions.filter(Boolean) : [];
            setChecks(Array.isArray(data?.checks) ? data.checks : []);
            setGuardReport(data?.guard_report || null);
            const ready = data?.status === 'ready';
            setStatus({
              text: ready
                ? '条件检查通过，可以生成可编辑流程。'
                : nextActions.join(' ') || `检查状态：${data?.status || '未知'}`,
              ok: ready,
            });
            if (ready) setCheckedSpec(JSON.stringify(spec));
          } catch (error) {
            setStatus({ text: `检查失败：${error?.message || error}`, ok: false });
          } finally {
            setChecking(false);
          }
        };

        const runBuild = async () => {
          const spec = buildSpec();
          if (JSON.stringify(spec) !== checkedSpec) return;
          setBuilding(true);
          setStatus({ text: '正在生成流程…', ok: true });
          try {
            const data = await requestJson('/studyui/api/material-tasks/build', {
              method: 'POST',
              headers: { 'content-type': 'application/json' },
              body: JSON.stringify({ session_id: sessionId, protocol: spec }),
            });
            const flowId = data?.flow_id;
            setCheckedSpec('');
            setStatus({
              text: `流程已生成（${flowId}）。请打开左侧“工作流画布”查看参数并运行。`,
              ok: true,
            });
            window.dispatchEvent(new CustomEvent('studyui-flow-created', { detail: { flowId } }));
          } catch (error) {
            setStatus({ text: `生成失败：${error?.message || error}`, ok: false });
          } finally {
            setBuilding(false);
          }
        };

        if (!open) return null;

        const columns = Array.isArray(preview?.columns) ? preview.columns : [];
        const rows = Array.isArray(preview?.preview) ? preview.preview : [];
        const busy = uploading || previewing || checking || building || sessionLoading;
        const specKey = JSON.stringify(buildSpec());
        const buildEnabled =
          sessionState === 'ready' && Boolean(checkedSpec) && checkedSpec === specKey && !busy;
        const field = (label, control, hint) =>
          h(
            'label',
            { style: MODAL_STYLE.field },
            h('span', { style: MODAL_STYLE.fieldLabel }, label),
            control,
            hint ? h('span', { style: MODAL_STYLE.fieldHint }, hint) : null,
          );
        const select = (value, onChange, options, props = {}) =>
          h(
            'select',
            { ...props, value, onChange, style: MODAL_STYLE.input },
            options.map(([optionValue, optionLabel]) =>
              h('option', { key: optionValue, value: optionValue }, optionLabel),
            ),
          );
        const isMechanics = task === 'mechanics';
        const guardFindings = Array.isArray(guardReport?.findings) ? guardReport.findings : [];
        const guardBlocked = guardReport?.status === 'block' || guardReport?.passed === false;
        return h(
          Modal,
          {
            title: '材料参数表单',
            subtitle: '上传原始文件，选择列与方法参数，检查后生成可编辑工作流。',
            onClose,
            width: 920,
          },
          h(
            'form',
            { onSubmit: runCheck },
            h(
              'p',
              { style: { ...MODAL_STYLE.note, margin: '0 0 12px' } },
              sessionLoading
                ? '正在准备材料项目与会话…'
                : sessionState === 'ready' && sessionId
                  ? `材料会话已就绪（${sessionId.slice(0, 8)}…）。`
                  : '材料会话未就绪。',
            ),
            h(
              'div',
              { style: MODAL_STYLE.fieldGrid },
              field(
                '研究任务',
                select(task, change(setTask), [
                  ['mechanics', '力学性能'],
                  ['spectra', '光谱特征'],
                  ['xrd', 'XRD 表征'],
                ]),
              ),
              field(
                '数据文件',
                h('input', {
                  type: 'file',
                  accept: '.csv,.tsv,.txt,.dat,.xy,.xye,.xlsx,.xlsm',
                  disabled: sessionState !== 'ready' || uploading,
                  onChange: (event) => {
                    const file = event.target.files?.[0];
                    event.target.value = '';
                    if (file) void uploadFile(file);
                  },
                  style: { ...MODAL_STYLE.input, padding: '5px 7px' },
                }),
                filename ? `已选择：${filename}` : '支持 CSV、TSV、TXT、DAT、XY、XYE、XLSX。',
              ),
              field(
                '工作表',
                select(sheet, change(setSheet), [['', '默认工作表'], ...sheets.map((name) => [name, name])]),
                'Excel 文件预览后可切换工作表。',
              ),
              field(
                '表头所在行（从 1 开始）',
                h('input', {
                  type: 'number',
                  min: 1,
                  step: 1,
                  value: header,
                  onChange: change(setHeader),
                  style: MODAL_STYLE.input,
                }),
              ),
            ),
            h(
              'div',
              { style: { ...MODAL_STYLE.fieldGrid, marginTop: '12px' } },
              field(
                '文本格式',
                select(format, change(setFormat), [
                  ['auto', '自动识别'],
                  ['table', '带表头的表格'],
                  ['xy', '数值 XY（支持 # 仪器注释）'],
                ]),
              ),
              field(
                '数据预览',
                h(
                  'button',
                  {
                    type: 'button',
                    disabled: !path || busy,
                    onClick: () => void previewMaterial(),
                    style: {
                      ...MODAL_STYLE.ghostButton,
                      opacity: !path || busy ? 0.55 : 1,
                      alignSelf: 'flex-start',
                    },
                  },
                  previewing ? '读取中…' : '更新数据预览',
                ),
              ),
            ),
            h(
              'div',
              { style: { margin: '12px 0', maxHeight: '240px', overflow: 'auto' } },
              preview
                ? h(
                    'div',
                    null,
                    h(
                      'p',
                      { style: MODAL_STYLE.note },
                      `${preview.row_count ?? 0} 行 · ${columns.length} 列 · 显示前 ${rows.length} 行`,
                    ),
                    h(
                      'table',
                      {
                        style: {
                          width: '100%',
                          borderCollapse: 'collapse',
                          fontSize: '11px',
                        },
                      },
                      h(
                        'thead',
                        null,
                        h(
                          'tr',
                          null,
                          columns.map((column) =>
                            h(
                              'th',
                              {
                                key: column.name,
                                style: {
                                  padding: '5px 6px',
                                  borderBottom: '1px solid #e5e7eb',
                                  textAlign: 'left',
                                  whiteSpace: 'nowrap',
                                  color: '#384250',
                                },
                              },
                              `${column.name} · ${column.dtype} · 缺失 ${(
                                Number(column.missing_rate || 0) * 100
                              ).toFixed(1)}%`,
                            ),
                          ),
                        ),
                      ),
                      h(
                        'tbody',
                        null,
                        rows.map((row, rowIndex) =>
                          h(
                            'tr',
                            { key: rowIndex },
                            columns.map((column) =>
                              h(
                                'td',
                                {
                                  key: column.name,
                                  style: {
                                    padding: '5px 6px',
                                    borderBottom: '1px solid #f1f2f4',
                                    whiteSpace: 'nowrap',
                                  },
                                },
                                row[column.name] == null ? '—' : String(row[column.name]),
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                  )
                : h('p', { style: MODAL_STYLE.note }, '选择文件后显示前 20 行、列类型和缺失率。'),
            ),
            h(
              'div',
              { style: MODAL_STYLE.fieldGrid },
              field(
                '横坐标列',
                select(x, change(setX), [
                  ['', '请先上传并预览'],
                  ...columns.map((column) => [column.name, column.name]),
                ]),
              ),
              field(
                '信号列',
                select(y, change(setY), [
                  ['', '请先上传并预览'],
                  ...columns.map((column) => [column.name, column.name]),
                ]),
              ),
              field(
                '横坐标单位',
                h('input', {
                  type: 'text',
                  list: 'studyui-mt-x-units',
                  value: xUnit,
                  placeholder: '例如 fraction、nm、deg',
                  onChange: change(setXUnit),
                  style: MODAL_STYLE.input,
                }),
              ),
              field(
                '信号单位',
                h('input', {
                  type: 'text',
                  list: 'studyui-mt-y-units',
                  value: yUnit,
                  placeholder: '例如 MPa、counts',
                  onChange: change(setYUnit),
                  style: MODAL_STYLE.input,
                }),
              ),
            ),
            h(
              'datalist',
              { id: 'studyui-mt-x-units' },
              ['fraction', '%', 'nm', 'cm^-1', 'deg'].map((value) => h('option', { key: value, value })),
            ),
            h(
              'datalist',
              { id: 'studyui-mt-y-units' },
              ['MPa', 'GPa', 'Pa', 'counts', 'a.u.'].map((value) => h('option', { key: value, value })),
            ),
            h(
              'label',
              {
                style: {
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '8px',
                  margin: '12px 0',
                  fontSize: '11.5px',
                  color: '#61666b',
                  lineHeight: 1.5,
                },
              },
              h('input', {
                type: 'checkbox',
                checked: sort,
                onChange: (event) => {
                  setSort(event.target.checked);
                  invalidate();
                },
                style: { width: '15px', height: '15px', margin: '1px 0 0' },
              }),
              h('span', null, '按横坐标排序（仅用于已确认的单条曲线；循环与卸载数据应先分段）'),
            ),
            isMechanics
              ? h(
                  'fieldset',
                  { style: MODAL_STYLE.fieldset },
                  h('legend', { style: MODAL_STYLE.legend }, '弹性与屈服方法'),
                  h(
                    'div',
                    { style: MODAL_STYLE.fieldGrid },
                    field(
                      '弹性拟合区间起点',
                      h('input', {
                        type: 'number',
                        step: 'any',
                        value: fitMin,
                        placeholder: '使用上述横坐标单位',
                        onChange: change(setFitMin),
                        style: MODAL_STYLE.input,
                      }),
                    ),
                    field(
                      '弹性拟合区间终点',
                      h('input', {
                        type: 'number',
                        step: 'any',
                        value: fitMax,
                        placeholder: '使用上述横坐标单位',
                        onChange: change(setFitMax),
                        style: MODAL_STYLE.input,
                      }),
                    ),
                    field(
                      '偏移应变（fraction）',
                      h('input', {
                        type: 'number',
                        min: 0,
                        step: 'any',
                        value: offset,
                        placeholder: '0.2% 偏移对应 0.002',
                        onChange: change(setOffset),
                        style: MODAL_STYLE.input,
                      }),
                    ),
                  ),
                )
              : h(
                  'fieldset',
                  { style: MODAL_STYLE.fieldset },
                  h('legend', { style: MODAL_STYLE.legend }, '基线与峰提取'),
                  h(
                    'div',
                    { style: MODAL_STYLE.fieldGrid },
                    field(
                      '基线策略',
                      select(baseline, change(setBaseline), [
                        ['', '请选择'],
                        ['none', '不扣基线'],
                        ['linear', '端点线性基线'],
                      ]),
                    ),
                    field(
                      '峰突出度',
                      h('input', {
                        type: 'number',
                        min: 0,
                        step: 'any',
                        value: prominence,
                        placeholder: '使用上述信号单位',
                        onChange: change(setProminence),
                        style: MODAL_STYLE.input,
                      }),
                    ),
                  ),
                ),
            status && status.text
              ? h(
                  'div',
                  {
                    role: 'status',
                    'aria-live': 'polite',
                    style: status.ok ? MODAL_STYLE.info : MODAL_STYLE.error,
                  },
                  status.text,
                )
              : null,
            checks.length || guardReport
              ? h(
                  'div',
                  {
                    style: {
                      ...MODAL_STYLE.card,
                      maxHeight: '220px',
                      overflow: 'auto',
                      marginTop: '12px',
                    },
                  },
                  checks.map((check, index) =>
                    h(
                      'div',
                      { key: index, style: { margin: '3px 0' } },
                      `${check.outcome === 'pass' ? '✓' : '○'} ${check.expected || ''}${
                        check.suggested_action ? '：' + check.suggested_action : ''
                      }`,
                    ),
                  ),
                  guardReport && (guardReport.status !== 'pass' || guardFindings.length)
                    ? h(
                        'div',
                        {
                          style: {
                            marginTop: '8px',
                            padding: '7px 9px',
                            borderRadius: '8px',
                            border: `1px solid ${guardBlocked ? '#f3d6d2' : '#f0e2c8'}`,
                            background: guardBlocked ? '#fdf3f2' : '#fdf8ee',
                            color: guardBlocked ? '#a33' : '#8a6216',
                          },
                        },
                        h(
                          'strong',
                          null,
                          `${
                            guardBlocked ? '⛔ 运行时物理守卫阻断' : '⚠️ 运行时物理守卫提醒'
                          } (${guardReport.status || 'warn'})`,
                        ),
                        guardFindings.length
                          ? h(
                              'ul',
                              { style: { margin: '4px 0 0', paddingLeft: '18px' } },
                              guardFindings.map((finding, index) =>
                                h(
                                  'li',
                                  { key: index },
                                  `[${finding.code || 'GUARD'}] ${finding.message || ''}${
                                    finding.recommendation ? ' — 建议：' + finding.recommendation : ''
                                  }`,
                                ),
                              ),
                            )
                          : null,
                      )
                    : null,
                )
              : null,
            h(
              'div',
              {
                style: {
                  display: 'flex',
                  justifyContent: 'flex-end',
                  gap: '8px',
                  flexWrap: 'wrap',
                  marginTop: '16px',
                },
              },
              h('button', { type: 'button', style: MODAL_STYLE.ghostButton, onClick: onClose }, '关闭'),
              h(
                'button',
                {
                  type: 'submit',
                  disabled: !path || !sessionId || busy,
                  style: {
                    ...MODAL_STYLE.ghostButton,
                    opacity: !path || !sessionId || busy ? 0.55 : 1,
                  },
                },
                checking ? '检查中…' : '检查方法条件',
              ),
              h(
                'button',
                {
                  type: 'button',
                  disabled: !buildEnabled,
                  onClick: () => void runBuild(),
                  style: { ...MODAL_STYLE.primaryButton, opacity: buildEnabled ? 1 : 0.5 },
                },
                building ? '生成中…' : '生成可编辑流程',
              ),
            ),
          ),
        );
      };

      const GovernanceDialog = ({ open, onClose }) => {
        const [loading, setLoading] = react.useState(false);
        const [error, setError] = react.useState('');
        const [scope, setScope] = react.useState(null);
        const [evolution, setEvolution] = react.useState(null);

        react.useEffect(() => {
          if (!open) return undefined;
          let alive = true;
          setLoading(true);
          setError('');
          Promise.all([
            requestJson('/studyui/api/governance/scope'),
            requestJson('/studyui/api/governance/evolution'),
          ])
            .then(([scopeData, evolutionData]) => {
              if (!alive) return;
              setScope(scopeData);
              setEvolution(evolutionData);
            })
            .catch((failure) => {
              if (alive) setError(String(failure?.message || failure));
            })
            .finally(() => {
              if (alive) setLoading(false);
            });
          return () => {
            alive = false;
          };
        }, [open]);

        react.useEffect(() => {
          if (!open) return undefined;
          const onKey = (event) => {
            if (event.key === 'Escape') onClose();
          };
          window.addEventListener('keydown', onKey);
          return () => window.removeEventListener('keydown', onKey);
        }, [open]);

        if (!open) return null;

        const byType = scope?.summary?.by_type || {};
        const workflows = Array.isArray(scope?.workflows) ? scope.workflows : [];
        const pending = Array.isArray(evolution?.pending) ? evolution.pending : [];
        const applied = Array.isArray(evolution?.applied) ? evolution.applied : [];
        const other = Array.isArray(evolution?.other) ? evolution.other : [];
        const patches = Array.isArray(evolution?.patches) ? evolution.patches : [];
        const joinList = (value) => (Array.isArray(value) && value.length ? value.join('；') : '—');
        return h(
          Modal,
          {
            title: '适用边界 & 进化',
            subtitle: '资产图谱、材料任务适用范围与已知限制，以及声明式知识补丁状态。',
            onClose,
            width: 860,
          },
          loading ? h('p', { style: MODAL_STYLE.note }, '正在加载治理状态…') : null,
          error ? h('div', { style: MODAL_STYLE.error }, `加载失败：${error}`) : null,
          !loading && !error
            ? h(
                'div',
                null,
                h(
                  'div',
                  { style: MODAL_STYLE.info },
                  `工具 T:${byType.T || 0} · 知识卡 K:${byType.K || 0} · 工作流 W:${
                    byType.W || 0
                  } · 技能 S:${byType.S || 0} · 数据 D:${byType.D || 0} · 角色 R:${
                    byType.R || 0
                  } · 校验错误:${scope?.summary?.error_count ?? 0}`,
                ),
                h(
                  'div',
                  { style: MODAL_STYLE.sectionHeader },
                  h('h3', { style: MODAL_STYLE.sectionTitle }, '适用范围与边界（AssetGraph）'),
                  h('span', { style: MODAL_STYLE.muted }, `${workflows.length} 个工作流`),
                ),
                workflows.length
                  ? h(
                      'div',
                      { style: { maxHeight: '260px', overflow: 'auto' } },
                      workflows.map((workflow) =>
                        h(
                          'div',
                          { key: workflow.id, style: MODAL_STYLE.card },
                          h(
                            'strong',
                            { style: { fontSize: '12.5px' } },
                            `${workflow.title || workflow.id} (${workflow.id})`,
                          ),
                          h(
                            'div',
                            { style: { marginTop: '2px' } },
                            `适用范围：${joinList(workflow.applicability_scope)}`,
                          ),
                          h('div', null, `不支持场景：${joinList(workflow.out_of_scope_cases)}`),
                          h('div', null, `已知限制：${joinList(workflow.known_limitations)}`),
                        ),
                      ),
                    )
                  : h('p', { style: MODAL_STYLE.note }, '暂无适用范围记录。'),
                h(
                  'details',
                  { style: { marginTop: '10px' } },
                  h(
                    'summary',
                    { style: { cursor: 'pointer', fontSize: '12px', color: '#384250' } },
                    '查看完整 Markdown 边界声明',
                  ),
                  h(
                    'pre',
                    {
                      style: {
                        margin: '6px 0 0',
                        maxHeight: '220px',
                        overflow: 'auto',
                        whiteSpace: 'pre-wrap',
                        border: '1px solid #e5e7eb',
                        borderRadius: '8px',
                        background: '#f9fafb',
                        padding: '10px',
                        fontSize: '11px',
                        lineHeight: 1.5,
                      },
                    },
                    scope?.markdown || '暂无 Markdown 声明。',
                  ),
                ),
                h(
                  'div',
                  { style: MODAL_STYLE.sectionHeader },
                  h('h3', { style: MODAL_STYLE.sectionTitle }, '声明式知识进化（Evolution）'),
                  h(
                    'span',
                    { style: MODAL_STYLE.muted },
                    `模式：${evolution?.mode || 'manual'} · 待审批：${pending.length} · 已应用：${applied.length} · 其他：${other.length}`,
                  ),
                ),
                patches.length
                  ? h(
                      'div',
                      { style: { maxHeight: '240px', overflow: 'auto' } },
                      patches.map((record, index) => {
                        const patch = record?.patch || {};
                        const values = Array.isArray(patch.values) ? patch.values : [];
                        const patchId = record?.patch_id || patch.patch_id || `patch-${index}`;
                        return h(
                          'div',
                          { key: patchId, style: MODAL_STYLE.card },
                          h(
                            'div',
                            {
                              style: {
                                display: 'flex',
                                alignItems: 'baseline',
                                justifyContent: 'space-between',
                                gap: '8px',
                              },
                            },
                            h(
                              'strong',
                              { style: { fontSize: '12px' } },
                              `${patchId} (${record?.status || 'unknown'})`,
                            ),
                            h(
                              'span',
                              { style: { ...MODAL_STYLE.muted, fontSize: '10.5px' } },
                              record?.updated_at || '',
                            ),
                          ),
                          h(
                            'div',
                            { style: { ...MODAL_STYLE.muted, marginTop: '2px' } },
                            `${patch.target_asset_id || '—'} · ${patch.field || '—'}: ${
                              values.join('；') || '—'
                            }`,
                          ),
                        );
                      }),
                    )
                  : h('p', { style: MODAL_STYLE.note }, '暂无待审批或已应用的知识进化补丁。'),
              )
            : null,
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
        const [jobs, setJobs] = react.useState([]);
        const [error, setError] = react.useState('');
        const [status, setStatus] = react.useState(null);
        const [busy, setBusy] = react.useState('');
        const [materialOpen, setMaterialOpen] = react.useState(false);
        const [governanceOpen, setGovernanceOpen] = react.useState(false);
        const [exporting, setExporting] = react.useState(false);
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
        react.useEffect(() => {
          let alive = true;
          const loadJobs = () => {
            requestJson('/studyui/api/workflows/jobs')
              .then((data) => {
                if (alive) setJobs(Array.isArray(data?.jobs) ? data.jobs : []);
              })
              .catch(() => {
                /* the queue is best-effort in the panel */
              });
          };
          loadJobs();
          const timer = setInterval(loadJobs, 5000);
          return () => {
            alive = false;
            clearInterval(timer);
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
        const jobLabels = {
          queued: '排队中',
          running: '运行中',
          completed: '已完成',
          failed: '失败',
          cancelled: '已取消',
        };
        const formatJobTime = (value) => {
          if (!value) return '';
          const numeric = Number(value);
          const date = Number.isFinite(numeric) ? new Date(numeric * 1000) : new Date(value);
          return Number.isNaN(date.getTime())
            ? ''
            : date.toLocaleString([], { hour: '2-digit', minute: '2-digit' });
        };
        const sanitizeFilename = (value) =>
          String(value || 'DSH 会话')
            .replace(/[/\\?%*:|"<>]/g, '_')
            .slice(0, 80);
        const downloadMarkdown = (name, text) => {
          const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' });
          const url = URL.createObjectURL(blob);
          const anchor = document.createElement('a');
          anchor.href = url;
          anchor.download = name;
          document.body.appendChild(anchor);
          anchor.click();
          anchor.remove();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
        };
        const exportBrief = async () => {
          if (exporting) return;
          setExporting(true);
          try {
            const sessionId = currentSessionId();
            if (!sessionId) {
              setStatus({ text: '请先打开一个 DSH 会话后再导出简报。', ok: false });
              return;
            }
            let row;
            try {
              row = ctx.sessions.list.getSnapshot()?.byId?.[sessionId];
            } catch (_) {
              row = undefined;
            }
            const title = row?.title || row?.displayTitle || 'DSH 会话';
            const now = new Date().toLocaleString('zh-CN');
            let binding;
            try {
              binding = ctx.sessions.binding(sessionId);
            } catch (_) {
              binding = undefined;
            }
            let windowSnapshot;
            try {
              windowSnapshot = binding?.eventSource?.getSnapshot?.();
            } catch (_) {
              windowSnapshot = undefined;
            }
            let openState;
            try {
              openState = binding?.session?.getSnapshot?.()?.openState;
            } catch (_) {
              openState = undefined;
            }
            const entryCount =
              windowSnapshot && Array.isArray(windowSnapshot.entries) ? windowSnapshot.entries.length : 0;
            const historyLoaded = Boolean(windowSnapshot) && (entryCount > 0 || openState === 'open');
            if (historyLoaded) {
              const entries = Array.isArray(windowSnapshot.entries) ? windowSnapshot.entries : [];
              const messages = [];
              for (const entry of entries) {
                if (entry?.type !== 'event') continue;
                const event = entry.event;
                if (!event || (event.type !== 'user/message' && event.type !== 'assistant/message')) continue;
                const role = event.type === 'user/message' ? 'user' : 'assistant';
                const message = role === 'user' ? event.data : event.data?.message;
                if (role === 'user' && message?.source?.kind && message.source.kind !== 'user') continue;
                const text = (Array.isArray(message?.content) ? message.content : [])
                  .filter((block) => block?.type === 'text' && typeof block.text === 'string')
                  .map((block) => block.text)
                  .join('\n\n')
                  .trim();
                if (text) messages.push({ role, text });
              }
              const partial = windowSnapshot.hasMore ? '（仅已加载的消息窗口；较早历史未载入）' : '';
              const body = messages.length
                ? messages
                    .map(
                      (message, index) =>
                        `### ${
                          message.role === 'user' ? '👤 研究者提问' : '⚡ DSH 智能体分析'
                        } [步骤 ${index + 1}]\n\n${message.text}\n`,
                    )
                    .join('\n')
                : '暂无已加载的对话消息。\n';
              const markdown = `# StudyUI 材料科研简报 · ${title}\n\n> **DSH 会话**: ${sessionId}  \n> **生成时间**: ${now}  \n> **消息范围**: ${messages.length} 条已加载消息${partial}\n\n---\n\n## 核心研究对话\n\n${body}\n---\n*由 StudyUI · DSH 插件生成*\n`;
              downloadMarkdown(`StudyUI_简报_${sanitizeFilename(title)}.md`, markdown);
              setStatus({ text: `简报已导出（${messages.length} 条已加载消息）。`, ok: true });
              return;
            }
            const [jobData, flowData] = await Promise.all([
              requestJson('/studyui/api/workflows/jobs').catch(() => null),
              requestJson('/studyui/canvas/api/v1/flows/').catch(() => null),
            ]);
            const jobList = Array.isArray(jobData?.jobs) ? jobData.jobs : [];
            const flowList = Array.isArray(flowData) ? flowData : flowData?.flows || [];
            const jobLines = jobList.length
              ? jobList
                  .slice(0, 20)
                  .map(
                    (job) =>
                      `- ${job.name || job.flow_id} · ${jobLabels[job.status] || job.status}${
                        job.created_at ? ' · ' + formatJobTime(job.created_at) : ''
                      }${job.error ? ' · ' + job.error : ''}`,
                  )
                  .join('\n')
              : '暂无运行记录。';
            const flowLines = flowList.length
              ? flowList
                  .filter((flow) => !flow.is_component)
                  .slice(0, 30)
                  .map((flow) => `- ${flow.name || flow.id}${flow.updated_at ? ' · ' + flow.updated_at : ''}`)
                  .join('\n')
              : '暂无工作流。';
            const markdown = `# StudyUI 材料科研简报 · ${title}\n\n> **DSH 会话**: ${sessionId}  \n> **生成时间**: ${now}  \n> **说明**: 当前 DSH 客户端尚未加载该会话历史，以下内容来自侧车材料流程与运行记录。\n\n---\n\n## 运行记录\n\n${jobLines}\n\n## 工作流\n\n${flowLines}\n\n---\n*由 StudyUI · DSH 插件生成*\n`;
            downloadMarkdown(`StudyUI_简报_${sanitizeFilename(title)}.md`, markdown);
            setStatus({
              text: '当前 DSH 会话历史尚未在客户端加载，已改用侧车材料流程与运行记录生成简报。打开该会话后再导出可包含完整对话。',
              ok: false,
            });
          } catch (failure) {
            setStatus({ text: `导出简报失败：${failure?.message || failure}`, ok: false });
          } finally {
            setExporting(false);
          }
        };
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
        const toolbar = { display: 'flex', gap: '6px', flexWrap: 'wrap', justifyContent: 'flex-end' };
        const toolButton = { ...runButton, fontSize: '11.5px', padding: '5px 9px' };
        const primaryToolButton = {
          ...toolButton,
          border: '1px solid #29476f',
          background: '#29476f',
          color: '#ffffff',
          fontWeight: 600,
        };
        const recordRow = {
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '10px',
          padding: '8px 11px',
          border: '1px solid #e5e7eb',
          borderRadius: '10px',
          background: '#ffffff',
          marginBottom: '6px',
        };
        const recordMeta = { fontSize: '10.5px', color: '#81858c', marginTop: '2px' };
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
                {
                  style: {
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'flex-end',
                    gap: '8px',
                  },
                },
                h(
                  'div',
                  { style: toolbar },
                  h(
                    'button',
                    {
                      type: 'button',
                      style: primaryToolButton,
                      onClick: () => setMaterialOpen(true),
                    },
                    '材料参数表单',
                  ),
                  h(
                    'button',
                    {
                      type: 'button',
                      style: toolButton,
                      onClick: () => setGovernanceOpen(true),
                    },
                    '适用边界 & 进化',
                  ),
                  h(
                    'button',
                    {
                      type: 'button',
                      style: { ...toolButton, opacity: exporting ? 0.55 : 1 },
                      disabled: exporting,
                      onClick: () => void exportBrief(),
                    },
                    exporting ? '导出中…' : '导出简报',
                  ),
                ),
                h(
                  'div',
                  { style: statsRow },
                  h('span', { style: pill }, `${tasks.length} 个任务组`),
                  h('span', { style: pill }, `${taskCount} 个检查项`),
                  h('span', { style: pill }, `${datasets.length} 个示例数据`),
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
              'div',
              { style: sectionHeader },
              h('h3', { style: sectionTitle }, '运行记录'),
              h('span', { style: groupMeta }, '人工确认使用 DSH 原生审批 UI'),
            ),
            jobs.length === 0
              ? h('p', { style: emptyText }, '暂无材料流程或直接运行记录。')
              : jobs.slice(0, 8).map((job) =>
                  h(
                    'div',
                    { key: job.id, style: recordRow },
                    h(
                      'div',
                      { style: { minWidth: 0 } },
                      h(
                        'strong',
                        {
                          style: {
                            display: 'block',
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
                        { style: recordMeta },
                        `${jobLabels[job.status] || job.status}${
                          job.created_at ? ' · ' + formatJobTime(job.created_at) : ''
                        }${job.error ? ' · ' + job.error : ''}`,
                      ),
                    ),
                    h(
                      'span',
                      {
                        style: {
                          ...groupMeta,
                          flex: '0 0 auto',
                          fontFamily: MODAL_STYLE.mono.fontFamily,
                        },
                      },
                      job.flow_id ? `flow ${String(job.flow_id).slice(0, 8)}…` : '',
                    ),
                  ),
                ),
            h(
              'p',
              { style: footerNote },
              '点击任务或示例后，Agent 会在当前 DSH 会话中补齐输入、调用 MCP 工具并返回结果。需要选列、填单位、检查方法或生成流程时，使用上方“材料参数表单”；人工确认在 DSH 原生审批界面完成。',
            ),
          ),
          h(MaterialTaskDialog, {
            open: materialOpen,
            onClose: () => setMaterialOpen(false),
          }),
          h(GovernanceDialog, {
            open: governanceOpen,
            onClose: () => setGovernanceOpen(false),
          }),
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
