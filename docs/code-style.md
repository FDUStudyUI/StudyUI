# 代码风格与检查

Python 代码遵循 `packages/materials-quality/pyproject.toml` 中的 Ruff 配置：Python 3.10、
110 字符行宽，并检查代码错误、导入顺序和常见问题。`dev` 依赖与仓库依赖锁使用相同的
Ruff 版本，避免格式化结果因版本不同而变化。编辑器可读取根目录的 `.editorconfig`；
前端格式由 `.prettierrc.json` 定义。

安装开发依赖后，在 `packages/materials-quality/` 运行与 CI 一致的 Python 检查：

```sh
ruff check src components tests scripts examples
ruff check ../../scripts --config pyproject.toml
ruff format --check src components tests scripts examples
ruff format --check ../../scripts --config pyproject.toml
```

需要格式化时，去掉 `ruff format` 的 `--check`；也可以只指定本次修改的文件。
长字符串、SQL 和提示词换行时应保留原有内容，不能因为排版改变实际值。

前端格式化需要 Node.js 和 npm。在仓库根目录执行以下检查；Prettier 版本与 CI 固定一致：

```sh
npx --yes prettier@3.3.3 --check \
  packages/materials-quality/src/materials_quality/agent/ui/index.html \
  'packages/materials-quality/src/materials_quality/agent/ui/assets/*.js' \
  'packages/materials-quality/src/materials_quality/agent/ui/assets/*.css' \
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
