# 真实 Langflow 界面验收（2026-10-30）

真实 Langflow 1.13.0 网页、Chrome 156、Windows / Python 3.10.8 验收通过。通过原生文件选择器导入存储的工作流，在画布点击汇总节点运行，再从原生输出查看器复制 JSON、核对明细和中文摘要。没有用自制页面或直接执行函数代替界面验收，也没有用 API 代替导入、运行和读取结果。

| 流程 | 画布节点 / 连线 | 完成检查 | 发现数 | 结论 | 追溯一致性 |
|---|---|---|---|---|---|
| clean | 9 / 19 | 6 | 0 | passed=true | verified |
| dirty | 9 / 19 | 6 | 8 | passed=false | verified |
| corrected | 9 / 19 | 6 | 0 | passed=true | verified |

九个画布节点包含八个正式组件和一个内嵌模拟数据源。Materials Quality 菜单列出八个正式节点。通过真实参数编辑器将共享规则改成 unknown_check 后，出现 `checks must configure at least one supported check`，流程停止；恢复规则后重新得到八条发现。浏览器未捕获到 pageerror 或失败的 API HTTP 响应；业务错误通过流程状态呈现。

验收发现六项检查纵向排列在最小缩放下会截掉末尾节点，已改成两列三行布局并重新验收。上游失败提示框有自动消失动画，脚本在读取错误后直接恢复参数，避免点击正在消失的 Dismiss 按钮导致测试不稳定。

合并后回归另外复现了助手引导提示也使用 dialog 角色的情况。编辑窗口的关闭等待和输出查看现在只匹配带相应窗口控件的 dialog，避免把助手提示误判为未关闭的编辑器。两个真实浏览器 DOM 回归测试确定性覆盖这个定位边界，真实 Langflow 端到端验收继续单独执行。

定位回归可运行 `python -m pytest tests/test_ui_selectors.py -q`。需安装 ui-test extra 及 Playwright Chromium；Windows 使用系统 Chrome 时，先设置 `$env:PLAYWRIGHT_CHROME_EXECUTABLE='C:\Program Files\Google\Chrome\Application\chrome.exe'`。仅安装核心依赖时，这组浏览器回归会跳过。

## 可核查证据

- [机器验收结果](ui-evidence/acceptance.json)：实际结果、中文摘要、浏览器版本、导入文件 SHA-256、页面错误列表。
- [环境版本](ui-evidence/environment.json)，完整 Windows 依赖快照另见 requirements-ui-tested-py310.txt。
- [八个组件菜单与完整画布](ui-evidence/01-component-menu.png)。
- [dirty 的追溯报告](ui-evidence/dirty-provenance.png)、[八条问题明细](ui-evidence/dirty-findings.png)、[中文摘要](ui-evidence/dirty-summary.png)。
- [corrected 通过报告](ui-evidence/corrected-provenance.png)、[修订后摘要](ui-evidence/corrected-summary.png)。
- [无效规则的界面提示](ui-evidence/invalid-rules.png)。
- 同目录的 clean/dirty/corrected-report.json 来自真实界面的“Copy output”，保留完整检查参数和规则快照。

## 复现

在包根目录，用隔离虚拟环境安装：

```powershell
$env:PYTHONUTF8 = '1'
python -m pip install '.[langflow,dev,ui-test]'
$env:LANGFLOW_COMPONENTS_PATH = (Resolve-Path components).Path
New-Item -ItemType Directory -Force artifacts/ui-runtime | Out-Null
$env:LANGFLOW_CONFIG_DIR = (Resolve-Path artifacts/ui-runtime).Path
$env:LANGFLOW_AUTO_LOGIN = 'true'
$env:LANGFLOW_DO_NOT_TRACK = 'true'
$env:LITELLM_LOCAL_MODEL_COST_MAP = 'True'
python -m langflow run --host 127.0.0.1 --port 7867 --no-open-browser
```

自动登录仅用于该 loopback 隔离验收服务。另开同环境终端：

```powershell
python -m scripts.ui_acceptance --chrome-executable 'C:\Program Files\Google\Chrome\Application\chrome.exe'
```

没有已安装的 Chrome 时，运行 `python -m playwright install chromium`，然后省略 --chrome-executable。脚本默认将新证据写入 artifacts/ui-acceptance/，不会覆盖已提交证据。它会在隔离服务中创建名称含随机后缀的验收流程。

GitHub Actions 增加独立 ui job，使用同一脚本和真实 Chromium；运行时测试、wheel 验证在 test job。云端 job 的结果以实际 Actions 记录为准。

本次验证原生组件、数据追溯和模拟案例交互；未验证团队尚未确认的其他 Langflow 版本、真实实验结论或 Agent 自主规划。源文件 SHA-256 是来源记录，verified 表示报告身份与参数一致，不是文件真实性认证。
