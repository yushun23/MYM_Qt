# MYM2 开发进度

> 最后更新：2026-07-04

---

## 里程碑进度

| 步骤 | 内容 | 状态 | 完成日期 | Git Commit |
|------|------|------|----------|------------|
| 00 | 工程基线 | ✅ 完成 | 2026-07-04 | `0084fd1` |
| 01 | 最小可启动 GUI | ✅ 完成 | 2026-07-04 | 待提交 |
| 02 | 数据库基座 | ✅ 完成 | 2026-07-04 | 待提交 |
| 03 | 账户与分类 CRUD | ⏳ 待开始 | — | — |
| 04 | 流水核心 | ⏳ 待开始 | — | — |
| 05 | 仪表盘 | ⏳ 待开始 | — | — |
| 06 | 流水完善 | ⏳ 待开始 | — | — |
| 07 | 应收管理 | ⏳ 待开始 | — | — |
| 08 | 预算模块 | ⏳ 待开始 | — | — |
| 09 | 报表 | ⏳ 待开始 | — | — |
| 10 | 设置页面 | ⏳ 待开始 | — | — |
| 11 | 导入/导出 | ⏳ 待开始 | — | — |
| 12 | 备份恢复 | ⏳ 待开始 | — | — |
| 13 | 数据迁移器 | ⏳ 待开始 | — | — |
| 14 | 图表完善 | ⏳ 待开始 | — | — |
| 15 | 测试覆盖 | ⏳ 待开始 | — | — |
| 16 | AI 助手（可选） | ⏳ 待开始 | — | — |
| 17 | 发布准备 | ⏳ 待开始 | — | — |

---

## 第 02 步完成详情

### 新增/修改文件

**数据库层：**
| 文件 | 说明 |
|------|------|
| `src/mym2/db/__init__.py` | db 包 |
| `src/mym2/db/engine.py` | SQLite 引擎工厂（PRAGMA foreign_keys/WAL/busy_timeout） |
| `src/mym2/db/session.py` | 线程安全 scoped_session 工厂 |
| `src/mym2/db/base.py` | DeclarativeBase + UUIDMixin + TimestampMixin |
| `src/mym2/db/migrate.py` | Alembic 自动 upgrade head 封装 |
| `src/mym2/db/models/__init__.py` | 10 个模型导出 |
| `src/mym2/db/models/account.py` | Account 模型 |
| `src/mym2/db/models/category.py` | Category 模型（树形自引用） |
| `src/mym2/db/models/transaction.py` | Transaction 模型（5 索引） |
| `src/mym2/db/models/budget.py` | BudgetPeriod + BudgetLine |
| `src/mym2/db/models/app_setting.py` | AppSetting（仅非秘密配置） |
| `src/mym2/db/models/import_run.py` | ImportRun 导入记录 |
| `src/mym2/db/models/legacy.py` | LegacyIdMap + LegacyArchiveRecord |
| `src/mym2/db/models/audit_event.py` | AuditEvent 审计事件 |

**Alembic 迁移：**
| 文件 | 说明 |
|------|------|
| `alembic.ini` | Alembic 配置 |
| `alembic/env.py` | 自定义 env（使用 MYM2 Base.metadata） |
| `alembic/script.py.mako` | 迁移模板 |
| `alembic/versions/81c53c9ecdc7_01_initial_schema.py` | 初始迁移：10 表 + 5 索引 |

**测试：**
| 文件 | 说明 |
|------|------|
| `tests/test_database.py` | 15 个数据库测试 |

**修改的文件：**
| 文件 | 说明 |
|------|------|
| `src/mym2/bootstrap.py` | 集成 `upgrade_to_head` 启动时自动迁移 |
| `pyproject.toml` | 添加 mym2.db + mym2.db.models 包 |
| `tests/test_app_startup.py` | UI 测试跳过 auto_migrate |

### 模型清单（10 张表）

| 表 | 金额列（INTEGER 分） | 说明 |
|----|---------------------|------|
| accounts | opening_balance_minor, current_balance_minor | 账户 |
| categories | — | 分类 |
| transactions | amount_minor | 流水 |
| budget_periods | — | 预算期间 |
| budget_lines | amount_minor | 预算明细 |
| app_settings | — | 非秘密设置 |
| import_runs | — | 导入记录 |
| legacy_id_map | — | 旧ID映射 |
| legacy_archive_records | — | 旧数据归档 |
| audit_events | — | 审计事件 |

### 验收结果
- ✅ `ruff check .` — All checks passed
- ✅ `python -m pytest` — **47 passed**
- ✅ `alembic upgrade head` — 10 表 + 5 索引创建成功
- ✅ `PRAGMA integrity_check` — ok
- ✅ `PRAGMA foreign_key_check` — 0 行
- ✅ schema 无 REAL 金额列
- ✅ 所有 `*_minor` 列类型为 INTEGER
- ✅ 每个测试使用隔离数据库

---

## 变更记录

| 日期 | 步骤 | 变更说明 |
|------|------|----------|
| 2026-07-04 | 00 | 建立工程基线 |
| 2026-07-04 | 01 | 可启动 GUI 空壳 |
| 2026-07-04 | 02 | SQLAlchemy 2.0 + Alembic 数据库基座 — 10 表 + 47 测试 |
