# v1.7.3 Verified Command Manifest

所有命令在 `/Users/jiayuanren/项目规划/.worktrees/integration-v1.7.3` 运行。唯一允许的 Python 解释器为：

```text
/Users/jiayuanren/项目规划/.venv/bin/python
```

## Import boundary

共享 `.venv` 的 editable `workbench` 默认指向主 checkout。pytest 从当前 worktree 的 `pyproject.toml` 读取 `pythonpath = ["backend", "."]`，但直接 `python -c` 不会获得该路径。

因此，所有直接导入 `workbench` 的 C1 Python 命令必须显式使用：

```bash
PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -c '...'
```

pytest 命令也以 `PYTHONPATH=backend` 调用，以把执行来源固定为当前 Integration worktree。

## 已验证基线命令

```bash
git rev-parse origin/main
git tag --points-at origin/main
git status --short
git diff --name-only origin/main -- tests/test_honest_did_adversarial.py tests/test_honest_did_sd_adversarial.py
PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -c 'import statsmodels; from statsmodels.regression.mixed_linear_model import MixedLM; print(statsmodels.__version__); print(MixedLM.__module__)'
PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -c 'import workbench.engine.stages.estimation; from workbench.engine.registry import MODEL_REGISTRY; assert "linear_mixed_effects" not in MODEL_REGISTRY; print(sorted(MODEL_REGISTRY))'
```

预期：发布基线为 `4b2e6c1d9ddd289005b84c186255fec2e9cbd86a`、tag 包含 `v1.7.2`、Integration clean、受保护文件无 diff、statsmodels 为 `0.14.6`、当前 bootstrap 后 registry 不含 `linear_mixed_effects`。

## C1 验证顺序

1. 先跑目标 test 的 RED，确认失败来自缺失 contract/seam，而不是 import 或环境。
2. 每个最小 GREEN 后重跑该目标 test。
3. 每个 Integration commit 后跑相应 OLS regression；central adapter/registry 改动会使相关 Evaluation evidence 失效。
4. C1 candidate 需通过 contracts、fixtures、feasibility 和 seam tests，再运行 `git diff --check`、受保护文件 diff 和 clean status。

禁止在这些命令中读取 API key、调用 provider、创建 local `.venv`、安装 package 或重新安装 `node_modules`。
