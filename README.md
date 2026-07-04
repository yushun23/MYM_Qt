# MYM2 — 个人记账软件

MYM2 是新一代桌面个人记账软件，从旧系统完全重建，使用 PySide6 + SQLAlchemy + SQLite 构建。

---

## 当前状态

> 🚧 **第 00 步：工程基线已建立。** 业务功能尚未实现。

| 里程碑 | 状态 |
|--------|------|
| 00 — 工程基线 | ✅ 完成 |
| 01 — 最小可启动 GUI | ⏳ 待开始 |
| 02–17 | ⏳ 待开始 |

---

## 快速开始（第 00 步后）

### 环境要求

- Python 3.12（推荐）或 3.11
- 虚拟环境（推荐 `venv`）

### 安装与运行

```bash
# 1. 创建虚拟环境
python3.12 -m venv .venv
source .venv/bin/activate

# 2. 安装开发依赖
pip install -e ".[dev]"

# 3. 运行测试
python -m pytest

# 4. （第 01 步后可启动程序）
# python -m mym2.app
```

---

## 旧系统数据迁移

如果你有旧 MYM（Flet 版）的账套文件：

1. 将旧 `.mym` 文件**复制**到 `legacy_input/my_money.mym`
2. 将旧源码复制到 `legacy_input/MYM-main/`（可选）
3. 迁移功能将在第 13 步实现

⚠️ **始终使用副本**，不要移动或删除你的原始文件。

---

## 刻意取消的功能

| 功能 | 原因 |
|------|------|
| 股票/证券模块 | 不再维护，历史数据仅归档 |
| Flet 框架 | 已迁移到 PySide6 |
| 在线图表 CDN | 改用离线 ECharts |

---

## 项目结构

```
mym2/
├── docs/           # 设计文档与约束
├── src/mym2/       # 源代码
├── tests/          # 测试
├── resources/      # 静态资源（含离线 ECharts）
├── scripts/        # 辅助脚本
└── legacy_input/   # 旧系统输入（不被跟踪）
```

---

## 开发

详见 `docs/REBUILD_SPEC.md` 和 `docs/PROJECT_CONTRACT.md`。

开发按 `PROGRESS.md` 中记录的里程碑逐步推进。
