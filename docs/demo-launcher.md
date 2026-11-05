# 安装、运行与排障

## 环境要求

当前启动器以 Python 3.10 验收。Windows 需要 Python Launcher (`py`) 或 `python` 命令；macOS/Linux 需要 `python3.10` 或 `python3`。依赖安装使用专用 `.demo-venv`，首次安装需联网下载 LFX、画布资源和科学计算包。

环境配置随源码维护：仓库根目录 `.python-version` 记录本机验收版本 3.10.22；组件包的 `pyproject.toml` 声明依赖范围，`requirements.lock` 保存跨平台解析结果，`requirements-tested-py310.txt` 和 `requirements-ui-tested-py310.txt` 保存 Python 3.10 验收快照。后者包含完整画布和科学计算环境。启动器仍根据 `pyproject.toml` 在专用 `.demo-venv` 中安装，锁文件用于复现已验收依赖与审查升级差异。更新依赖时应同步刷新相应锁文件并运行测试。

服务只监听本机回环地址：StudyUI 主界面默认 `http://127.0.0.1:7880`，工作流画布通过同一服务的 `/canvas/` 提供。只需确保一个端口空闲。

## 首次安装

Windows，在仓库根目录：

```powershell
.\start_demo.bat --setup
```

macOS/Linux：

```sh
sh ./start_demo.sh --setup
```

启动器只向仓库的 `.demo-venv` 安装 `packages/materials-quality[langflow,science,instruments]` 和 `langflow-base==1.13.0`。没有安装成功时，检查错误信息及 `.demo-runtime/logs/studyui-launcher.log`，修复网络或系统依赖后重试。

## 正常启动与停止

Windows：

```powershell
.\start_demo.bat
```

macOS/Linux：

```sh
sh ./start_demo.sh
```

浏览器打开 `http://127.0.0.1:7880`，在 StudyUI 左侧进入“工作流画布”。启动终端显示 `StudyUI and workflow canvas ready` 后，保持终端开启；在该窗口按 `Ctrl+C` 停止服务。启动器只停止自己创建的进程，不接管同端口的既有服务。

## 检查环境

Windows：

```powershell
.\start_demo.bat --check
```

macOS/Linux：

```sh
sh ./start_demo.sh --check
```

检查模式只读取 Python 版本、依赖和端口，不建目录、不安装包、不启动服务、不导入或修改工作流。`required_missing` 表示启动阻断项；`optional_missing` 表示 h5py、netCDF4 或 zarr 等可选仪器数据能力缺少依赖。

## 配置模型

启动后，在 StudyUI 右上角进入“设置 → 模型管理”，填写名称、API 地址、模型名和密钥，点击“保存模型”，再点“测试连接”。DeepSeek 可使用 `https://api.deepseek.com` 和 `deepseek-flash`。API 密钥保存到 Windows Credential Manager 或系统凭据库，不写入工作流文件、SQLite 会话库或 Git；可以留空以继续使用该配置中已保存的密钥。对外部模型服务的聊天和经过审批的 AI 分析会把相应消息/数据发送给该服务。

可保存多个配置并切换。远程模型地址必须使用 HTTPS；HTTP 仅允许 `localhost`、`127.0.0.1` 或 `::1`。

## 数据位置

- 根目录 `workflows/`：每个项目工作流一个 JSON 文件；版本快照在 `.history/`，删除流程进入 `.trash/`。
- 根目录 `workspace.json`：项目和排序信息。
- `.demo-runtime/agent.sqlite3`：StudyUI 会话、审批与调用审计。
- `.demo-runtime/studyui-settings.json`：非密钥模型配置和权限设置。
- 系统凭据库：模型 API 密钥。
- `.demo-runtime/skills/`：用户导入的 Skills、哈希信任状态与旧版本副本。

启动器只会在 `workflows/` 没有 JSON 工作流时初始化仓库示例，不覆盖现有流程。当前示例 DNA Origami 工作流从论文公开的 Figure 3 CSV 源数据生成，保留逐文件 SHA-256 校验。根目录本机工作流和工作区均为运行数据，默认不会提交。

## 常见问题

| 现象 | 处理方式 |
|---|---|
| 找不到 Python 3.10 | 安装 Python 3.10，并确认 `py -3.10`（Windows）或 `python3.10`（macOS/Linux）可用。 |
| `required_missing` 非空 | 在仓库根目录执行 `--setup`；若依赖安装中断，处理网络或编译依赖后重试。 |
| `optional_missing` 非空 | 仅在需要相应仪器数组格式时执行 `--setup` 更新环境；普通科研示例不受影响。 |
| 7880 已占用 | 选择空闲端口，例如 `--port 7886`。启动器不会复用或终止该端口现有服务。 |
| StudyUI 界面打开但模型不可用 | 检查设置中的 API 地址、模型名与凭据，然后使用“测试连接”；远端地址必须 HTTPS。 |
| 含脚本 Skill 无法运行 | 选择“审核后沙箱 Skill”，对当前版本进行信任审批，并确保 Docker 已安装、镜像已预拉取。无 Docker 时会拒绝执行。 |
| 内部画布打不开或工作流报错 | 查看 `.demo-runtime/logs/studyui-launcher.log` 与 `.demo-runtime/logs/studyui-server.log`；确认工作流节点都来自已安装 StudyUI 组件，并检查项目归属与输入文件路径。 |

## 其他启动选项

启动器默认目录均按仓库路径解析。可以更换运行目录和端口：

```powershell
.\start_demo.bat --runtime "D:\StudyUI运行数据" --port 7886
```

已有依赖齐全的 Python 3.10 环境可只读运行：

```powershell
.\start_demo.bat --python "D:\Python310\python.exe"
```

此模式不会向外部解释器安装依赖；不能与 `--setup` 同时使用。启动参数和检查退出码见 `scripts/start_demo.py --help`。
