# 评委本地演示启动器

需要 Python 3.10。默认服务地址为 <http://127.0.0.1:7880>，仅监听本机，不自动打开浏览器。首次安装需要联网，依赖下载时间取决于网络。Windows 支持中文和空格目录。

在仓库根目录双击 `start_demo.bat`，或执行：

```powershell
.\start_demo.bat --setup
```

启动器会明确显示安装目标 `.demo-venv`，安装当前 `packages/materials-quality[langflow,science,instruments]` 与 `langflow-base==1.13.0`。已有完整专用环境会直接复用。普通启动脚本无参数等同于 `--setup`，因此首次双击可完成安装并启动。终端显示 `Demo ready` 后，打开打印的地址。保持该终端运行，按 Ctrl+C 停止本次服务。

Linux/macOS 使用 Python 3.10 执行：

```sh
sh ./start_demo.sh --setup
```

只检查已有环境（不会安装、建目录、启动服务或导入流程）：

```powershell
.\start_demo.bat --check
```

也可从任意目录直接运行 Python 入口，所有默认目录均按仓库路径解析：

```powershell
py -3.10 -B "完整仓库路径\scripts\start_demo.py" --check
```

`--check` 即使与 `--setup` 同时出现也始终只读。退出码 `0` 表示必需依赖与端口检查通过；`2` 表示缺失或不兼容、端口占用、参数/启动错误。`required_missing` 列出阻断启动的 Python/Langflow/科学核心依赖，`optional_missing` 列出可选的 h5py、netCDF4、zarr 仪器数组文件能力。可选缺失不阻断三个核心演示；使用相关数组文件功能前应完成 `--setup`。

复用已经安装依赖的 Python 3.10 解释器：

```powershell
.\start_demo.bat --python "D:\已有环境\.venv\Scripts\python.exe" --check
.\start_demo.bat --python "D:\已有环境\.venv\Scripts\python.exe"
```

`--python` 必须指向解释器文件。启动器不会向该环境安装或升级任何依赖，且拒绝同时使用 `--python --setup`。服务的 `PYTHONPATH` 指向当前仓库包源码，组件使用当前仓库的副本，因此演示运行当前版本。

高级参数：

```powershell
.\start_demo.bat --port 7886 --runtime "D:\演示数据\科研 Skill"
```

已有 `.demo-venv` 时，上述命令直接启动；首次使用请加 `--setup`。`--runtime` 可指定独立运行目录；默认 `.demo-runtime` 包含数据库 `langflow.db`、组件副本 `components/`、配置 `config/`、日志 `logs/`、临时文件 `tmp/` 与 pip 缓存 `pip-cache/`。`.demo-venv` 与 `.demo-runtime` 已被 Git 忽略。启动器不修改系统环境变量；启动子进程时会替换继承的 Langflow 配置，以免误用其他工作区的数据库。仅固定专用虚拟环境可作为安装目标，现成解释器的虚拟环境标识与前缀会在安装前检查。安装子进程清除继承的 pip/Python 安装重定向变量、禁用外部 pip 配置文件，并显式限定安装前缀、禁止用户级安装和限定缓存目录。

端口被占用时，启动器会停止并提示使用 `--port`，不会接管已有服务。慢机器可加 `--ready-timeout 480`。服务启动日志在 `logs/launcher-server.log`，Langflow 日志在 `logs/langflow.log`。

服务就绪后，启动器仅通过本次新启动的本机服务的 `auto_login` 与 `flows` API 导入：

- `packages/materials-quality/examples/skill_flows/spectra.json`
- `packages/materials-quality/examples/skill_flows/mechanics.json`
- `packages/materials-quality/examples/skill_flows/contrast.json`

已有同名流程会保留，不覆盖编辑。终端分别显示实际导入和已保留的名称。如果自动导入失败，会明确显示未完成，并打印三个 JSON 文件的绝对路径；在 Langflow 的新建/上传流程入口手动导入即可。自动导入不等于执行流程；进入画布后按流程说明运行。

验证范围：自动测试覆盖只读检查、依赖阻断与可选提示、安装隔离、中文空格路径、非法/占用端口，以及用本机 HTTP 测试服务确认同名保留和缺失流程创建。Windows 使用现有 Python 3.10 环境执行真实启动与流程 API 回读；不会为验收向该环境安装依赖。全新环境网络下载与 Linux/macOS 包装器需在目标机器验收。
