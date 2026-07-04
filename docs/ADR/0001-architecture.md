# ADR 0001：MYM2 系统架构决策

> 状态：已采纳 | 日期：2026-07-04

---

## 背景

MYM2 是从旧 Python + Flet + SQLite 个人记账系统完全重建的项目。需要在一开始确定核心技术架构、分层策略和数据流，确保后续开发方向一致。

---

## 决策

### 1. GUI 框架：PySide6 + Qt Widgets

**选择**：PySide6（Qt for Python 官方绑定），使用 Qt Widgets 而非 Qt Quick/QML。

**理由**：
- Qt Widgets 提供成熟、稳定的桌面控件集，适合数据密集型应用。
- PySide6 是 Qt 官方 Python 绑定，LGPL 许可，社区活跃。
- `QStackedWidget` 天然支持多页面导航。
- 与 `QWebEngineView` 配合可嵌入 ECharts 图表。

**排除的选项**：
- Flet：旧系统使用，新系统弃用。
- Tkinter：控件老旧，无 WebEngine。
- Electron：过重，不符合 Python 技术栈。
- Qt Quick/QML：学习曲线高，对数据表单类 UI 无优势。

---

### 2. 分层架构：UI → Service → Repository → DB

**选择**：严格的四层架构。

```
┌──────────────────────┐
│   UI (PySide6)       │  用户交互、数据展示
├──────────────────────┤
│   Service            │  业务逻辑、事务管理、校验
├──────────────────────┤
│   Repository         │  数据查询封装（只读）
├──────────────────────┤
│   DB (SQLAlchemy)    │  ORM 模型、迁移
└──────────────────────┘
```

**理由**：
- 职责分离：UI 不直接操作数据库。
- 可测试性：每层可独立测试。
- 写账安全：Service 是唯一写入口。
- 领域模型（Pydantic）在 Service 和 UI 之间传递，DB 模型不出 UI 层。

---

### 3. 数据库：SQLite + SQLAlchemy 2.0 + Alembic

**选择**：SQLite 作为嵌入式数据库，SQLAlchemy 2.0 ORM 作为访问层，Alembic 管理 schema 迁移。

**理由**：
- SQLite 零配置、单文件、适合个人桌面应用。
- SQLAlchemy 2.0 提供类型安全的查询 API。
- Alembic 是 SQLAlchemy 官方迁移工具，确保 schema 变更可追溯、可回滚。

**金额约束**：所有金额列为 `INTEGER`（分），禁止 `REAL`/`FLOAT`。

---

### 4. 图表方案：QWebEngineView + 本地 ECharts

**选择**：使用 `QWebEngineView` 加载本地 HTML 页面，内嵌 `echarts.min.js`（存放于 `resources/vendor/`）。

**理由**：
- ECharts 提供丰富的图表类型和交互。
- 本地文件加载，无需网络，无需 CDN。
- `QWebEngineView` 与 Qt Widgets 无缝集成。
- Python 端生成 ECharts option JSON，通过 `QWebChannel` 或 `runJavaScript` 传递。

**排除的选项**：
- pyecharts：依赖在线 CDN，需要额外处理离线；直接生成 option JSON 更可控。
- Qt Charts：图表类型有限，交互弱于 ECharts。
- matplotlib：非交互式，不适合仪表盘。

---

### 5. 金额处理：整数分 + Decimal

**选择**：
- 数据库存储 `INTEGER` 分。
- Python 解析/运算使用 `Decimal`。
- UI 显示时转为元（÷100 格式化），统一工具函数处理。

**理由**：
- 避免浮点舍入误差（经典财务系统做法）。
- `Decimal` 提供精确十进制运算。
- 禁止 `float` 和 `REAL` 杜绝隐患。

---

### 6. 股票模块：完全移除

**选择**：新系统不复现任何功能性股票模块。

**理由**：
- 旧股票功能依赖外部数据源和复杂业务逻辑。
- 用户明确要求不再维护股票功能。
- 历史数据通过归档和快照保留资产核算连续性。

---

## 后果

### 正面
- 清晰的分层边界便于团队协作和测试。
- 离线图表方案无网络依赖。
- 整数分避免浮点问题。
- 移除股票模块降低复杂度。

### 负面
- 分层架构增加初期代码量。
- QWebEngineView 打包体积较大（~80MB）。

### 风险缓解
- 通过脚手架和模板代码减少重复。
- QWebEngineView 作为可选依赖打包。

---

## 替代方案

| 方案 | 为何不采纳 |
|------|-----------|
| FastAPI + Web UI | 用户需求为桌面应用 |
| Tkinter | 控件过时，无 WebEngine |
| Flet | 旧系统框架，弃用 |
| Electron + Python 后端 | 架构复杂，两个进程 |
| 直接 SQL 无 ORM | 缺少迁移管理和类型安全 |

---

> 本 ADR 为 MYM2 架构基础。后续重大决策应追加到 `docs/ADR/`。
