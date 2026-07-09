# docs/superpowers — 文档分类与生命周期约定

> 目的：这几类文档生命周期不同，混在一起会烂账（旧快照没人清、债没人勾）。
> 本文件定义约定，新对话/收尾时照此维护，避免再次堆积。

## 四类文档

| 目录 | 是什么 | 生命周期 | 维护规则 |
|---|---|---|---|
| `handoff/` | "在某版本怎么起手"的快照 | 一次性，下一份出来即作废 | **只留最新一份 live**，旧的移 `archive/handoff/` |
| `followups/` | 某版本评审记下的债 | 逐项到解决为止 | **只保留最新版本那份**当 live 滚动 backlog，见下 |
| `roadmap/` | 长期产品/技术方向（含 `architecture-debt.md` 架构债台账） | 长活 | 就地更新，不归档 |
| `archive/` | 已冻结的历史 handoff / followups / 复盘 | immutable | 只读留痕，不再维护 |

## followups = 单一滚动 backlog（核心约定）

**开着的债只放一个地方**：最新版本的 `followups/vX.Y.Z-followups.md` 就是当前 live
backlog。规则：

1. 所有还开着的债都收在这份 live 文件里，每条标注来源版本。
2. **做完就删**——git 历史留痕，不靠 `[x]` 勾（实践证明没人回去勾，checkbox 状态不可信）。
3. 下个版本起手：把新债续在**同一份** live 文件（或新建 vX.Y.(Z+1) 并把上一份未清的债滚过来）。
4. 版本收尾、且该份债确实清空/冻结时，整份移进 `archive/followups/`。

> 反面教材（整理前的状态）：v1.4.1/v1.5.0/v1.5.1/v1.6.5/v1.6.8 各一份 followups，
> 里面 14+ 个 `[ ]` 没人勾，分不清哪些早随后续版本做完了。2026-07-08 整理时逐份核销：
> 只有 v1.5.0 的 REV-3 经代码核实仍未解决 → 滚进当时的 live backlog（v1.6.8-followups §5），
> 其余全部冻结进 `archive/`。

## handoff = 只留最新

起手快照天然"最新即权威"。收尾发版后，旧 handoff 移 `archive/handoff/`；`archive/` 里的
仍可作历史背景查阅（新 handoff 通常会显式引用旧的作为背景）。
