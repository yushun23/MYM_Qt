# MYM2 重建规格书（REBUILD SPEC）

> 版本：1.0.0 | 最后更新：2026-07-04

---

## 1. 项目概述

MYM2 是从旧 Python + Flet + SQLite 个人记账系统完全重建的新版本。重建原则：

- **不修改旧系统**：旧源码和旧账套仅作为迁移输入，存放于 `legacy_input/`。
- **全量重写**：不复制旧代码；参考旧逻辑但用新架构重写。
- **范围收缩**：移除不再需要的股票/证券功能。

---

## 2. 目标模块

### 2.1 核心模块（按优先级）

| 序号 | 模块 | 说明 |
|------|------|------|
| 1 | **仪表盘** (Dashboard) | 净资产概览、月度收支、最近流水、图表卡片 |
| 2 | **流水** (Transactions) | 收支/转账/应收记录、筛选、搜索、分页 |
| 3 | **账户与分类** (Accounts & Categories) | CRUD 管理、余额快照 |
| 4 | **应收** (Receivables) | 垫付/还款跟踪 |
| 5 | **预算** (Budget) | 月度预算设定与实际对比 |
| 6 | **报表** (Reports) | 分类饼图、趋势折线、收支对比 |
| 7 | **设置** (Settings) | 主题、语言、数据目录、备份路径 |
| 8 | **导入/导出** (Import/Export) | Excel 导出、旧账套迁移导入 |
| 9 | **备份恢复** (Backup & Restore) | 数据库备份/恢复 |
| 10 | **AI 助手** (可选) | AI 对话记账、智能分类（最后实现） |

### 2.2 明确排除

- ❌ 股票/证券功能（持仓、行情、交易、证券导入、月度结算、网络报价）
- ❌ Flet 框架及任何 Flet 组件
- ❌ 旧 `stock_*` 表的业务逻辑恢复
- ❌ 在线图表 CDN 依赖

---

## 3. 目录与职责边界

```
mym2/
├── docs/                    # 设计与约束文档
│   └── ADR/                 # 架构决策记录
├── src/mym2/
│   ├── __init__.py
│   ├── app.py               # QApplication 启动入口
│   ├── main_window.py       # QMainWindow + 导航 + QStackedWidget
│   ├── ui/                  # UI 层（每个页面一个文件）
│   │   ├── dashboard/
│   │   ├── transactions/
│   │   ├── accounts/
│   │   ├── categories/
│   │   ├── receivables/
│   │   ├── budget/
│   │   ├── reports/
│   │   ├── settings/
│   │   ├── import_export/
│   │   └── backup/
│   ├── db/                  # 数据库层
│   │   ├── base.py          # DeclarativeBase, engine, session
│   │   ├── models/          # SQLAlchemy ORM 模型
│   │   └── migrations/      # Alembic 迁移（由 alembic 生成）
│   ├── domain/              # 领域模型 / Pydantic schemas
│   ├── services/            # 业务服务层
│   │   ├── ledger_service.py    # 唯一写账入口
│   │   ├── account_service.py
│   │   ├── category_service.py
│   │   ├── budget_service.py
│   │   ├── report_service.py
│   │   └── import_service.py
│   ├── repositories/        # 数据访问层（只读查询）
│   ├── importers/           # 导入器（旧账套迁移、Excel）
│   ├── charts/              # ECharts option 生成与 QWebEngineView 封装
│   ├── resources/           # Qt 资源文件、图标
│   └── utils/               # 工具函数（金额格式化、日期等）
├── tests/                   # 测试
├── scripts/                 # 辅助脚本
├── resources/vendor/        # 第三方前端库（echarts.min.js）
└── legacy_input/            # 旧系统输入（不跟踪）
```

### 职责边界

| 层 | 可以 | 不可以 |
|----|------|--------|
| **UI** | 渲染、收集用户输入、调用 Service | 直接写数据库、执行 SQL |
| **Service** | 业务逻辑、调用 Repository、管理事务 | 直接操作 Qt Widget |
| **Repository** | 封装查询、返回领域对象 | 包含业务逻辑 |
| **Domain** | 数据验证、类型定义 | 访问数据库或 UI |
| **DB Models** | 表映射、关系定义 | 包含业务逻辑 |

---

## 4. 关键领域模型草案（文档级，非代码）

### 4.1 Account（账户）
- `id`：主键
- `name`：账户名称
- `type`：账户类型枚举（`cash`/`bank`/`credit_card`/`investment_snapshot`/`receivable`）
- `balance`：当前余额（整数分）
- `currency`：货币代码（默认 CNY）
- `is_editable`：是否可编辑（历史快照账户为 False）
- `created_at`/`updated_at`

### 4.2 Category（分类）
- `id`：主键
- `name`：分类名
- `type`：`expense` / `income`
- `parent_id`：父分类（自引用）
- `color`：展示颜色

### 4.3 Transaction（流水）
- `id`：主键
- `account_id`：关联账户
- `category_id`：关联分类
- `type`：`expense`/`income`/`transfer`/`receivable_advance`/`receivable_repayment`/`balance_adjustment`/`historical_investment_settlement`
- `amount`：金额（整数分）
- `note`：备注
- `transacted_at`：交易日期
- `created_at`/`updated_at`

### 4.4 BudgetPeriod（预算期间）
- `id`：主键
- `year`/`month`：预算所属年月
- `created_at`

### 4.5 BudgetLine（预算明细）
- `id`：主键
- `budget_period_id`：关联预算期间
- `category_id`：关联分类
- `amount`：预算金额（整数分）

### 4.6 ImportRun（导入运行记录）
- `id`：主键
- `source`：来源标识
- `status`：`dry_run`/`completed`/`failed`/`rolled_back`
- `rows_imported`/`rows_skipped`/`rows_failed`
- `started_at`/`finished_at`
- `report_json`：详细报告

### 4.7 LegacyIdMap（旧 ID 映射）
- `id`：主键
- `old_table`：旧表名
- `old_id`：旧记录 ID
- `new_table`：新表名
- `new_id`：新记录 ID
- `import_run_id`：关联导入运行

### 4.8 LegacyArchiveRecord（旧数据归档）
- `id`：主键
- `old_table`：旧表名
- `old_id`：旧记录 ID
- `data_json`：原始数据 JSON
- `import_run_id`：关联导入运行

### 4.9 AuditEvent（审计事件）
- `id`：主键
- `action`：操作类型（`create`/`update`/`delete`）
- `entity_type`：实体类型
- `entity_id`：实体 ID
- `changes_json`：变更内容
- `created_at`

---

## 5. 交易类型草案

| 类型 | 说明 | 金额符号 |
|------|------|----------|
| `expense` | 支出 | 正数（减少资产） |
| `income` | 收入 | 正数（增加资产） |
| `transfer` | 转账 | 从一个账户到另一账户 |
| `receivable_advance` | 应收垫付 | 记录代付 |
| `receivable_repayment` | 应收还款 | 记录还款 |
| `balance_adjustment` | 余额调节 | 手动调节余额 |
| `historical_investment_settlement` | 历史投资结算快照 | 仅迁移时使用 |

---

## 6. 口径原则

### 6.1 余额
- 账户余额 = 该账户所有已确认流水的代数和。
- 初始化余额通过 `balance_adjustment` 类型流水体现。
- 迁移时可能通过 `historical_investment_settlement` 建立不可编辑快照。

### 6.2 净资产
- 净资产 = Σ 所有活跃账户余额。
- 投资快照账户计入净资产。

### 6.3 预算
- 预算对比仅基于已分类的 `expense` 类型流水。
- 转账和调节不计入预算对比。

### 6.4 报表
- 报表数据由 Service 层聚合，Repository 层提供原始查询。
- 图表渲染使用离线 ECharts option JSON。

---

## 7. 开发里程碑（第 00–17 步）

| 步骤 | 内容 | 产出 |
|------|------|------|
| **00** | 工程基线 | 目录、文档、pyproject.toml、测试骨架、Git 初始化 |
| **01** | 最小可启动 GUI | QMainWindow + QStackedWidget + 空占位页面 |
| **02** | 数据库基础 | SQLAlchemy Base、engine、session、Alembic 初始化 |
| **03** | 账户与分类 CRUD | 模型、Service、Repository、UI 页面 |
| **04** | 流水核心 | Transaction 模型、LedgerService、基本流水录入 UI |
| **05** | 仪表盘 | 净资产卡片、最近流水、月度汇总 |
| **06** | 流水完善 | 筛选、搜索、分页、编辑、删除 |
| **07** | 应收管理 | 垫付/还款模型与 UI |
| **08** | 预算模块 | 月度预算设定、实际对比 |
| **09** | 报表 | 分类饼图、趋势折线、ECharts 集成 |
| **10** | 设置页面 | 主题、数据路径、偏好 |
| **11** | 导入/导出 | Excel 导出、旧系统迁移 |
| **12** | 备份恢复 | 数据库备份与恢复 |
| **13** | 数据迁移器 | 旧 .mym → 新 .db 迁移工具 |
| **14** | 图表完善 | ECharts 离线集成、交互优化 |
| **15** | 测试覆盖 | 单元测试、集成测试、UI 测试 |
| **16** | AI 助手（可选） | AI 对话记账 |
| **17** | 发布准备 | 打包、文档终稿、发布 |

---

## 8. 开发流程

1. 每步开始前阅读相关 `docs/` 和已有代码。
2. 实现完成后运行该步骤验收测试及全量已有测试。
3. 更新 `PROGRESS.md` 并提交 Git commit。
4. 按固定格式报告完成情况。

---

> 本文档随项目推进持续更新。架构决策请写入 `docs/ADR/`。
