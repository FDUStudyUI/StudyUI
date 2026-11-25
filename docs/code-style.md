# 代码风格与检查

Python 代码遵循 `materials-quality/pyproject.toml` 中的 Ruff 配置：Python 3.10、
110 字符行宽，并检查代码错误、导入顺序和常见问题。`dev` 依赖与仓库依赖锁使用相同的
Ruff 版本，避免格式化结果因版本不同而变化。编辑器可读取根目录的 `.editorconfig`；
前端格式由 `.prettierrc.json` 定义。

安装开发依赖后，在 `materials-quality/` 运行与 CI 一致的 Python 检查：

```sh
ruff check src components tests scripts examples
ruff check ../scripts --config pyproject.toml
ruff format --check src components tests scripts examples
ruff format --check ../scripts --config pyproject.toml
```

需要格式化时，去掉 `ruff format` 的 `--check`；也可以只指定本次修改的文件。
长字符串、SQL 和提示词换行时应保留原有内容，不能因为排版改变实际值。

前端格式化需要 Node.js 和 npm。在仓库根目录执行以下检查；Prettier 版本与 CI 固定一致：

```sh
npx --yes prettier@3.3.3 --check \
  materials-quality/src/materials_quality/agent/ui/index.html \
  'materials-quality/src/materials_quality/agent/ui/assets/*.js' \
  'materials-quality/src/materials_quality/agent/ui/assets/*.css' \
  'scripts/assets/*.html' \
  '.github/workflows/*.yml' \
  .prettierrc.json
```

将 `--check` 换成 `--write` 可自动格式化这些前端文件。Windows PowerShell 用户可将该命令
写在一行，或将续行符 `\` 替换为反引号。

不要重新格式化 `agent/ui/assets/vendor/` 中的第三方资源：其原始字节受完整性清单保护。
`.prettierignore` 还排除了生成的组件、示例流程、数据集、工作流和本机运行数据；需要更新
这些内容时，应使用相应的 `scripts/build_*.py` 脚本或应用本身。完成修改后运行相关测试，
涉及界面时还应运行浏览器回归测试。

科学组件与 `science/catalog.json` 由源 CATALOG 生成，禁止手改生成文件。修改节点定义后先
再生成，并用 `--check` 确认没有漂移（CI 也执行该检查）：

```sh
python materials-quality/scripts/build_science_components.py
python materials-quality/scripts/build_science_components.py --check
```

分类使用稳定的英文 ID（`category`），中文展示名在 `category_label`；新增分类时同步更新
`src/materials_quality/science/categories.py`。

## 命名、注释与语法约定

- **命名**：公共 API、配置键、序列化字段和工作流 JSON 字段不得为了"好看"改名；内部函数与
  变量用短而明确的名字（避免 30 个字符以上的重复描述），私有实现统一加 `_` 前缀。不要为同一
  概念保留两个近义命名。
- **注释**：注释只解释"为什么"和约束，不复述代码；不保留注释掉的旧代码。模块首行是一句话
  概述。代码注释用英文，用户界面与用户文档用中文。
- **语法**：优先现代、直接的写法（f-string、字典/列表推导、`contextlib.suppress`、三元
  表达式、`zip(..., strict=True)`）。这些由 Ruff 的 `UP`/`SIM`/`C4`/`PIE`/`RUF` 规则自动
  检查，`python -m ruff check --fix` 可安全修复大部分。
- **统一性**：所有 `src/` 模块包含 `from __future__ import annotations`；行宽 110；导入由
  Ruff 统一排序。生成文件（组件、catalog、示例流程）由生成器维护，不手工修改。
