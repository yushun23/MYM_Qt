# MYM2 开发进度

> 最后更新：2026-07-04

---

## 里程碑进度

| 步骤 | 内容 | 状态 | 完成日期 | Git Commit |
|------|------|------|----------|------------|
| 00 | 工程基线 | ✅ 完成 | 2026-07-04 | `0084fd1` |
| 01 | 最小可启动 GUI | ✅ 完成 | 2026-07-04 | 待提交 |
| 02 | 数据库基座 | ✅ 完成 | 2026-07-04 | 待提交 |
| 03 | 领域模型、金额规则与统一账本服务 | ✅ 完成 | 2026-07-04 | 待提交 |
| 04 | 旧.mym 只读检查器与迁移前报告 | ✅ 完成 | 2026-07-04 | 待提交 |
| 05 | 迁移映射与可验证 dry-run | ✅ 完成 | 2026-07-04 | 待提交 |
| 06 | 执行迁移、回滚、报告与导入向导 | ✅ 完成 | 2026-07-04 | 待提交 |
| 07 | 账户、分类与历史归档 | ✅ 完成 | 2026-07-04 | 待提交 |
| 08 | 日常流水（新增/筛选/编辑/删除/导出） | ✅ 完成 | 2026-07-04 | 待提交 |
| 09 | 离线 ECharts 与仪表盘 | ✅ 完成 | 2026-07-04 | 待提交 |
| 10 | 预算模块 | ✅ 完成 | 2026-07-04 | 待提交 |
| 11 | 应收管理 | ✅ 完成 | 2026-07-04 | 待提交 |
| 12 | 导入/导出 | ⏳ 待开始 | — | — |
| 13 | 备份恢复 | ⏳ 待开始 | — | — |
| 14 | 数据迁移器 | ⏳ 待开始 | — | — |
| 15 | 图表完善 | ⏳ 待开始 | — | — |
| 16 | 测试覆盖 | ⏳ 待开始 | — | — |
| 17 | AI 助手（可选） | ⏳ 待开始 | — | — |
| 18 | 发布准备 | ⏳ 待开始 | — | — |

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

## 第 11 步完成详情

### 新增/修改文件

**服务层：**
| 文件 | 说明 |
|------|------|
| `src/mym2/services/receivable_service.py` | ReceivableService：垫付/还款/删除/查询/汇总，委托 LedgerService 写账 |
| `src/mym2/services/validators.py` | 修正 `validate_account_for_transaction_type` 对 receivable_advance/receivable_repayment 的验证逻辑 |

**仓储层：**
| 文件 | 说明 |
|------|------|
| `src/mym2/repositories/receivable_repo.py` | ReceivableRepository：应收账户/流水只读查询 |
| `src/mym2/repositories/__init__.py` | 导出 ReceivableRepository |

**服务层（修改）：**
| 文件 | 说明 |
|------|------|
| `src/mym2/services/__init__.py` | 导出 ReceivableService |

**UI 页面：**
| 文件 | 说明 |
|------|------|
| `src/mym2/ui/pages/receivables_page.py` | 完整应收管理页面：待收列表/历史流水/债务人汇总三标签页，新增垫付/收回欠款对话框（支持部分/全部还款），删除流水，筛选（债务人/类型/日期范围），双击快速还款 |

**测试：**
| 文件 | 说明 |
|------|------|
| `tests/test_receivable_service.py` | 20 个集成测试 |

### 功能实现

**ReceivableService：**
- `advance()`：垫付/借出，资金从现金/银行卡流入应收账户
- `repay()`：收回欠款，从应收账户流回收款账户，支持部分/全部还款
- `delete_receivable_transaction()`：删除应收相关流水（仅限 receivable_advance/receivable_repayment 类型）
- `get_receivable_accounts()`：获取所有 receivable 类型账户
- `get_receivable_balance()`：查询应收余额
- `get_receivable_transactions()`：按债务人/类型/日期范围查询应收流水
- `get_pending_receivables()`：获取有未收余额的债务人汇总
- `get_all_receivable_summaries()`：获取全部债务人汇总（含已结清）
- `build_transaction_views()`：构建 UI 视图对象
- `get_non_receivable_asset_accounts()`：获取可用于垫付/还款的非应收资产账户

**应收页面（ReceivablesPage）：**
- 三个标签页：待收列表、历史流水、债务人汇总
- 新增垫付对话框：选择债务人 + 资金来源 + 金额 + 日期 + 备注
- 收回欠款对话框：选择债务人 + 收款账户 + 金额（留空=全部收回）+ 日期 + 备注
- 全部收回复选框：自动填满当前待收余额
- 历史流水筛选：债务人/类型（垫付/还款）/日期范围
- 双击表格行快速还款
- 删除选中流水（确认对话框）
- 余额实时刷新

**安全规则遵守：**
- 所有写操作通过 ReceivableService → LedgerService，UI 不直写数据库
- 普通流水编辑器阻止将 expense/income 写入应收账户（validate_account_not_receivable）
- 还款金额不超过当前应收余额（服务层验证）
- 垫付资金来源不能是应收账户（验证）
- 还款收款方不能是应收账户（验证）
- 删除只允许 receivable_advance/receivable_repayment 类型

### 验收结果
- ✅ `ruff check .` — All checks passed
- ✅ `python -m pytest` — **413 passed**（+20 新增应收测试）
- ✅ 部分还款后余额准确
- ✅ 全部还款后余额归零
- ✅ 删除垫付后余额恢复归零
- ✅ 删除还款后余额恢复原始值
- ✅ 不能将普通支出写入应收账户（ValueError）
- ✅ 不能将普通收入写入应收账户（ValueError）
- ✅ 垫付资金来源为应收账户时被拒绝
- ✅ 还款收款方为应收账户时被拒绝
- ✅ 多次垫付/还款后余额与逐笔重算一致

### 变更记录更新

| 日期 | 步骤 | 变更说明 |
|------|------|----------|
| 2026-07-04 | 11 | 应收管理 — ReceivableService + ReceivableRepository + ReceivablesPage + 20 测试 |

---

## 变更记录

| 日期 | 步骤 | 变更说明 |
|------|------|----------|
| 2026-07-04 | 00 | 建立工程基线 |
| 2026-07-04 | 01 | 可启动 GUI 空壳 |
| 2026-07-04 | 02 | SQLAlchemy 2.0 + Alembic 数据库基座 — 10 表 + 47 测试 |

---

## 第 03 步完成详情

### 新增/修改文件

**领域层（domain/）：**
| 文件 | 说明 |
|------|------|
| `src/mym2/domain/__init__.py` | domain 包 |
| `src/mym2/domain/enums.py` | TransactionType, AccountType, CategoryType, AuditAction 枚举 + 辅助判断函数 |
| `src/mym2/domain/money.py` | Money 值对象（不可变）、`from_decimal_text()`、`format()`、`validate_positive_amount_minor()` |

**服务层（services/）：**
| 文件 | 说明 |
|------|------|
| `src/mym2/services/__init__.py` | services 包 |
| `src/mym2/services/dto.py` | CreateTransactionDTO, UpdateTransactionDTO |
| `src/mym2/services/validators.py` | 账户可写/分类相容/流水可编辑/应收隔离等验证器 |
| `src/mym2/services/balance_service.py` | 余额从流水重算：资产/负债方向规则、调节/结算特殊处理 |
| `src/mym2/services/ledger_service.py` | 唯一写账入口：create/update/delete + 事务 + 审计事件 |

**数据访问层（repositories/）：**
| 文件 | 说明 |
|------|------|
| `src/mym2/repositories/__init__.py` | repositories 包 |
| `src/mym2/repositories/account_repo.py` | AccountRepository（只读查询 + 余额更新） |
| `src/mym2/repositories/category_repo.py` | CategoryRepository（只读查询） |
| `src/mym2/repositories/transaction_repo.py` | TransactionRepository（只读查询 + 汇总） |

**测试：**
| 文件 | 说明 |
|------|------|
| `tests/test_money.py` | 37 个测试：解析、格式化、算术、边界异常 |
| `tests/test_ledger_service.py` | 24 个测试：收支/转账/信用卡/编辑/删除/验证/回滚/重算 |

**修改的文件：**
| 文件 | 说明 |
|------|------|
| `pyproject.toml` | 添加 mym2.domain、mym2.repositories、mym2.services 包 |

### 领域规则实现

**交易类型（7 种）：**
| 类型 | 用途 | 余额影响方向 |
|------|------|-------------|
| expense | 支出 | 资产账户余额减少；负债账户余额增加（欠款增多） |
| income | 收入 | 资产账户余额增加；负债账户余额减少（还款） |
| transfer | 转账 | 转出账户余额减少，转入账户余额增加（资产/负债方向按规则） |
| receivable_advance | 应收垫付 | 资产账户→应收账户 |
| receivable_repayment | 应收还款 | 应收账户→资产账户 |
| balance_adjustment | 余额调节 | 直接累加到 account_out |
| historical_investment_settlement | 历史投资结算 | 仅迁移，锁定不可编辑 |

**余额规则：**
- 资产账户（cash/bank/investment_snapshot/receivable）：支出/转出→余额减少，收入/转入→余额增加
- 负债账户（credit_card）：消费→余额增加（欠款），还款→余额减少
- income 当 account_out==account_in 时仅计一次（外部资金流入）
- balance_adjustment / historical_investment_settlement 直接累加

**写账安全：**
- 所有写操作通过 LedgerService（唯一入口）
- 每个写操作记录 AuditEvent
- 停用账户拒绝写入
- 不可编辑/锁定账户拒绝写入
- 历史结算流水不可编辑/删除
- 应收账户只能由应收专用服务写入（LedgerService 拒绝）
- 分类与交易类型相容性校验
- 转账要求两个不同账户

### 验收结果
- ✅ `ruff check .` — All checks passed
- ✅ `python -m pytest` — **114 passed**（+67 新增）
- ✅ 全部已有测试通过，零回归
- ✅ 金额解析：`"12.34"` → 1234 分，拒绝 NaN/科学计数法/超两位小数/空值
- ✅ 余额始终 = opening_balance + Σ signed contributions
- ✅ 资产支出/收入/转账/信用卡消费还款 全覆盖
- ✅ 编辑冲销/删除回滚/异常事务回滚 已验证
- ✅ 审计事件随 create/update/delete 记录


---

## 第 04 步完成详情

### 新增/修改文件

**导入器（importers/legacy_mym/）：**
| 文件 | 说明 |
|------|------|
| `src/mym2/importers/__init__.py` | importers 包 |
| `src/mym2/importers/legacy_mym/__init__.py` | legacy_mym 子包 |
| `src/mym2/importers/legacy_mym/source_reader.py` | 只读 SourceReader：mode=ro URI、哈希校验、SQL 安全检查 |
| `src/mym2/importers/legacy_mym/schema_probe.py` | SchemaProbe：表/列/行数统计、REAL 检测、交易类型、链接证券识别、余额差异、settings 脱敏 |
| `src/mym2/importers/legacy_mym/reporting.py` | ReportGenerator：JSON + Markdown 报告生成 |
| `src/mym2/importers/legacy_mym/audit.py` | 审计主入口 + CLI（`python -m mym2.importers.legacy_mym.audit`） |

**测试：**
| 文件 | 说明 |
|------|------|
| `tests/test_legacy_audit.py` | 31 个测试：只读打开、损坏拒绝、哈希不变、schema 探测、REAL/股票/余额差异、settings 脱敏、报告生成、端到端 |

**修改的文件：**
| 文件 | 说明 |
|------|------|
| `pyproject.toml` | 添加 `mym2.importers`、`mym2.importers.legacy_mym` 包 |

### 功能实现

**SourceReader（只读 SQLite 访问）：**
- `mode=ro` URI 打开，操作系统级读写保护
- 打开前校验文件头（`SQLite format 3` 魔数）
- 禁止写 SQL（INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/VACUUM 等）
- 仅允许只读 PRAGMA（table_info、integrity_check、foreign_key_check 等）
- 打开前后 SHA-256 哈希校验
- sqlite3.Row row_factory 支持按名称访问列

**SchemaProbe（深度探测器）：**
- 表清单与列详情（18 表检测）
- 行数统计（总计 6431 行）
- REAL 类型列检测（17 个金额相关 REAL 列异常标记）
- 交易类型分布（8 种类型，覆盖 Expense/Income/Transfer/垫付借出/收回欠款等）
- 链接证券账户识别（`linked_stock_account_id`、`is_system_locked`、`group_name`、`stock_*` 表）
- 账户余额按流水重算差异分析（非链接账户）
- Settings 敏感键检测（7 个敏感键识别，值一律不展示）

**ReportGenerator：**
- JSON 报告：机器可读，包含完整元数据
- Markdown 报告：人可读，9 个章节（文件信息/完整性/表概览/REAL风险/交易类型/链接证券/余额差异/Settings/警告）
- Settings 值绝对不展示（仅键名）

**CLI 命令：**
```bash
python -m mym2.importers.legacy_mym.audit legacy_input/my_money.mym --out reports/
```

### 验收结果
- ✅ `ruff check .` — All checks passed
- ✅ `python -m pytest` — **145 passed**（+31 新增）
- ✅ 损坏/非 SQLite 文件安全拒绝（错误消息不含堆栈泄露）
- ✅ 文件哈希审计前后一致（测试 fixture 验证通过）
- ✅ 报告有表清单、行数、异常、余额差异
- ✅ 没有生成新账本文件（`.db` 文件）
- ✅ Settings 敏感值完全不泄露（JSON 和 Markdown 均验证）
- ✅ 链接证券账户正确识别（1 个）
- ✅ CLI 对真实 `my_money.mym` 审计成功


---

## 第 05 步完成详情：迁移映射与可验证 dry-run

### 新增/修改文件

**新增文件：**
| 文件 | 说明 |
|------|------|
| `src/mym2/importers/legacy_mym/migration_plan.py` | MigrationPlan + TablePlan + AccountBalancePlan + PendingConfirmation + MigrationRisk 数据结构，支持 JSON 序列化/反序列化，稳定排序 |
| `src/mym2/importers/legacy_mym/validators.py` | 金额转换验证（Decimal(str(old))→分）、交易/账户类型映射、settings 白名单/黑名单、股票策略验证、余额确认构建 |
| `src/mym2/importers/legacy_mym/mapper.py` | LegacyMapper：旧库→新领域模型映射器，优先级映射（accounts/categories/transactions/budget_*），股票归档，settings 白名单过滤，未知表/类型标记"需确认" |
| `src/mym2/importers/legacy_mym/migration_service.py` | MigrationService：dry-run 编排器，在内存临时 DB 中验证映射，幂等性检查，`dry_run_migration()` 便捷函数 |

**测试文件：**
| 文件 | 说明 |
|------|------|
| `tests/test_migration_dryrun.py` | 77 个测试：MigrationPlan 序列化、金额转换、类型映射、Settings 白名单、LegacyMapper 全表计划、MigrationService dry-run、幂等性、股票策略对比 |

**修改的文件：**
| 文件 | 说明 |
|------|------|
| `src/mym2/importers/legacy_mym/__init__.py` | 更新 docstring 包含新模块 |

### 功能实现

**MigrationPlan（可序列化迁移计划）：**
- TablePlan：每张表待迁移/归档/跳过/失败/需确认数量
- AccountBalancePlan：每个账户的旧余额、新余额（分）、重算余额（分）、差额
- PendingConfirmation：未知表/未知类型/余额差异/未分类 settings
- MigrationRisk：精度风险/未知类型风险/余额差异风险/股票差异风险
- 稳定排序：table_plans 按表名、account_balance_plans 按 legacy_id、其它按分类+名称
- JSON 序列化使用 `sort_keys=True`

**迁移映射规则：**
- 优先表：accounts → categories → transactions → budget_months → budget_items → budget_lines
- 金额转换：`Decimal(str(old_real)) * 100` → 量化到整数 → 记录 ≥1 分差异
- 保留 source_table、legacy_id、原始日期/类型信息
- 已知交易类型 8 种映射；未知类型记录为"需确认"，不猜测
- 已知账户类型 4 种映射；未知类型默认 cash + 确认项

**股票处理：**
- 默认策略 `historical_snapshot`：链接证券账户 → 不可编辑 `investment_snapshot` 类型账户
- 若流水重算余额 ≠ 旧余额 → 计划生成 `historical_investment_settlement` 调节流水，补齐差额
- 股票原始表全部归档到 `legacy_archive_records`
- 另提供 `archive_only`（仅归档，不创建快照）和 `skip`（跳过全部股票）策略

**Settings 白名单：**
- 允许：theme、language、font_size、font_family、currency_display、date_format、backup_path 等
- 强制跳过：password_hash、api_key、proxy_password、token、secret、session、pending_action 等

**AI 聊天：**
- `ai_chat_messages` / `ai_imported_records` → 写入通用归档（`legacy_archive_records`），不进入新 AI 上下文

**Dry-Run 编排：**
- SourceReader 只读打开 → LegacyMapper 构建计划 → 内存临时 DB schema 验证
- 不写入任何目标业务数据（`.db` 文件）
- 幂等性验证：两次连续 dry-run JSON 计划一致
- `dry_run_migration()` 便捷函数支持直接输出 JSON 文件

### 验收结果
- ✅ `ruff check .` — All checks passed
- ✅ `python -m pytest` — **222 passed**（+77 新增）
- ✅ dry-run 不创建目标业务数据（`.db` 文件）
- ✅ 两次连续 dry-run JSON 计划在稳定排序下一致（幂等）
- ✅ settings 敏感值完全不泄露（API key、password_hash 等）
- ✅ 链接证券账户识别并标记 `is_linked_stock=True`
- ✅ `historical_snapshot` 策略生成调节流水计划补齐差额
- ✅ `archive_only` 和 `skip` 策略各自行为正确
- ✅ 未知表/未知交易类型记录为"需确认"，不静默丢弃
- ✅ 金额转换使用 `Decimal(str(old_value))`，量化差异追踪

### 变更记录更新

| 日期 | 步骤 | 变更说明 |
|------|------|----------|
| 2026-07-04 | 05 | 迁移映射与可验证 dry-run — MigrationPlan + LegacyMapper + MigrationService + 77 测试 |

---

## 第 06 步完成详情：执行迁移、回滚、报告与导入向导

### 新增/修改文件

**新增文件：**
| 文件 | 说明 |
|------|------|
| `src/mym2/importers/legacy_mym/executor.py` | MigrationExecutor — 真实迁移执行引擎：备份、事务包裹写入、失败回滚、迁移后验证、重复导入防护 |
| `src/mym2/ui/pages/import_wizard.py` | ImportWizard — PySide6 多步骤导入向导：选择文件→预检→策略→计划预览→确认→执行/结果 |
| `tests/test_migration_executor.py` | 22 个测试：完整迁移、余额核对、异常回滚、重复导入拒绝、股票策略对比、报告可追溯 |

**修改的文件：**
| 文件 | 说明 |
|------|------|
| `src/mym2/ui/main_window.py` | 添加"导入"导航项（ImportWizard 页面），导航项从 7→8 |
| `tests/test_app_startup.py` | 更新导航数量断言（7→8） |

### 功能实现

**MigrationExecutor（迁移执行引擎）：**
- `execute(backup=True)`：完整迁移流程
  - SQLite backup API 备份目标库
  - 运行 `upgrade_to_head` 初始化 schema
  - 事务包裹写入（`engine.begin()`），异常自动回滚
  - 迁移顺序：账户→分类→流水→预算→Settings→归档
  - `historical_snapshot` 策略生成调节流水
  - 写入 `ImportRun`、`LegacyIdMap`、`LegacyArchiveRecord`
  - 统一重算所有账户余额
- `_check_duplicate_import()`：拒绝同一源文件哈希重复导入到同一目标库
- `_verify_migration()`：FK 检查、完整性检查、交易计数、LegacyIdMap 唯一性
- `dry_run_plan()`：仅生成计划，不写入

**ImportWizard（PySide6 导入向导）：**
- 6 步页面流程：
  1. 选择 .mym 文件 + 目标账本路径
  2. 只读预检（后台线程执行 audit）
  3. 股票策略选择（默认 historical_snapshot，可选 archive_only/skip）
  4. 计划预览（后台 dry-run）
  5. 最终确认（备份选项 + 确认勾选框）
  6. 执行/结果页（后台线程迁移，进度条）
- 按钮明确区分："仅生成报告"（不导入） vs "导入到新账本"（执行迁移）
- 禁止默认自动导入
- 结果页显示成功/归档/跳过/失败计数 + FK/完整性验证

### 验收结果
- ✅ `ruff check .` — All checks passed
- ✅ `python -m pytest` — **244 passed**（+22 新增）
- ✅ 异常时目标无部分业务写入（事务回滚）
- ✅ 旧库文件哈希迁移前后不变
- ✅ 成功后报告可追溯（source_hash、import_run_id、stats、verification）
- ✅ 重复导入被拒绝（同一哈希+同一目标库）
- ✅ 所有股票原始行归档（`legacy_archive_records`），不功能化重建
- ✅ 链接证券账户 → 不可编辑 investment_snapshot + 调节流水
- ✅ Settings 敏感值（api_key、password_hash）不写入目标库
- ✅ `archive_only` 和 `skip` 策略各自行为正确

### 变更记录更新

| 日期 | 步骤 | 变更说明 |
|------|------|----------|
| 2026-07-04 | 06 | 执行迁移、回滚、报告与导入向导 — MigrationExecutor + ImportWizard + 22 测试 |

---

## 第 07 步完成详情：账户、分类与历史归档页面

### 新增/修改文件

**服务层（新增）：**
| 文件 | 说明 |
|------|------|
| `src/mym2/services/account_service.py` | AccountService — 账户 CRUD 唯一写入口：创建、编辑、启停，锁定/历史快照保护，审计事件 |
| `src/mym2/services/category_service.py` | CategoryService — 分类 CRUD 唯一写入口：创建、编辑、启停，系统分类保护，父分类验证 |

**DTO（修改）：**
| 文件 | 说明 |
|------|------|
| `src/mym2/services/dto.py` | 新增 CreateAccountDTO, UpdateAccountDTO, CreateCategoryDTO, UpdateCategoryDTO |

**服务包（修改）：**
| 文件 | 说明 |
|------|------|
| `src/mym2/services/__init__.py` | 导出 AccountService, CategoryService |

**UI 页面（新增）：**
| 文件 | 说明 |
|------|------|
| `src/mym2/ui/pages/accounts_page.py` | QTableView + AccountTableModel + AccountFilterProxy — 新建/编辑/启停账户，流水只读钻取，CSV 导出，历史归档入口 |
| `src/mym2/ui/pages/categories_page.py` | QTableView + CategoryTableModel + CatFilterProxy — 新建/编辑/启停分类，系统分类保护 |
| `src/mym2/ui/pages/history_archive_page.py` | 导入批次列表 + 归档记录只读查看，JSON/CSV 导出，Tab 分页，功能限制说明 |

**UI 页面（修改）：**
| 文件 | 说明 |
|------|------|
| `src/mym2/ui/pages/__init__.py` | 导出 CategoriesPage, HistoryArchivePage |
| `src/mym2/ui/pages/settings_page.py` | 添加"历史归档"入口卡片 |
| `src/mym2/ui/main_window.py` | 导航栏新增"分类""归档"两项（8→10），对接子页面 navigate_to 信号 |

**测试（新增）：**
| 文件 | 说明 |
|------|------|
| `tests/test_account_service.py` | 23 个测试：CRUD、启停、锁定保护、审计事件、DTO 验证 |
| `tests/test_category_service.py` | 16 个测试：CRUD、启停、系统分类保护、父分类验证 |
| `tests/test_ui_pages.py` | 20 个测试：模型列头、页面构造、导航禁止词、归档功能限制说明 |

**修改的文件：**
| 文件 | 说明 |
|------|------|
| `tests/conftest.py` | 新增 `session` fixture（独立临时数据库 + Alembic 迁移） |
| `tests/test_app_startup.py` | 导航项数量断言 8→10，预期列表增加"分类""归档" |
| `pyproject.toml` | ruff 配置：Qt 页面跳过 N802/N806/B008 规则 |

### 功能实现

**账户管理：**
- QTableView + QAbstractTableModel + AccountFilterProxy（禁用 QTableWidget）
- 支持 cash/bank/credit_card/investment_snapshot/receivable 账户类型
- 新建/编辑：名称、类型、分组、期初余额、币种、备注
- 编辑检测变化，仅更新改变的字段
- investment_snapshot 账户自动锁定+不可编辑
- 锁定账户 → 清晰中文提示拒绝编辑/启停
- 账户流水只读钻取（TransactionDialog）
- 按当前筛选导出 CSV
- 底部"历史归档"按钮跳转

**分类管理：**
- QTableView + QAbstractTableModel + CatFilterProxy
- 支持 expense/income/system 分类类型
- 新建/编辑：名称、类型、父分类、排序、颜色、图标
- 系统分类保护：不可修改名称/类型，不可启停
- 父分类自引用验证（不可设自己为父）

**历史归档：**
- Tab 分页：导入批次 + 归档记录
- 导入批次：查看来源、状态、计数、时间、详细报告（JSON）
- 归档记录：查看旧表名、旧 ID、摘要、原始 JSON
- 导出归档 JSON（完整结构化）和 CSV（扁平化）
- 页面声明："不提供持仓、行情、买卖、证券月结功能"
- 通过设置页卡片和账户页按钮双入口访问

**安全规则遵守：**
- 所有账户/分类写操作通过 AccountService/CategoryService
- UI 层不直写数据库
- 所有写操作产生 AuditEvent
- 导航与页面中无"股票""证券"等禁止词（归档中"历史证券"说明除外）

### 验收结果
- ✅ `ruff check .` — All checks passed
- ✅ `python -m pytest` — **303 passed**（+59 新增）
- ✅ 账户新增、编辑、启停可用
- ✅ 分类新增、编辑、启停可用
- ✅ 锁定账户编辑 → 中文提示拒绝
- ✅ 系统分类启停 → 中文提示拒绝
- ✅ 历史快照只读
- ✅ 导航不含股票字样
- ✅ QTableView + QAbstractTableModel（非 QTableWidget）
- ✅ CSV 导出按筛选输出

### 变更记录更新

| 日期 | 步骤 | 变更说明 |
|------|------|----------|
| 2026-07-04 | 07 | 账户、分类与历史归档页面 — AccountService/CategoryService + 3 个 UI 页面 + 59 测试 |


---

## 第 08 步完成详情：日常流水 — 新增、筛选、编辑、删除与导出

### 新增/修改文件

**仓储层（修改）：**
| 文件 | 说明 |
|------|------|
| `src/mym2/repositories/transaction_repo.py` | 新增 TransactionFilter、TransactionPage 数据类；新增 query_filtered 方法（日期范围、账户、分类、类型、关键词、清算状态筛选 + 稳定排序 + 分页）；新增 get_accounts_map/get_categories_map 辅助查询 |

**UI 页面（修改）：**
| 文件 | 说明 |
|------|------|
| `src/mym2/ui/pages/transactions_page.py` | 完整的流水管理页面：QTableView + TransactionTableModel + QSortFilterProxyModel；日期范围/账户/分类/类型/清算筛选栏；关键词搜索；分页控件；支出/收入/转账新增对话框（QDoubleValidator 两位小数、QDateEdit）；编辑/删除确认 + 锁定交易保护；CSV 导出（公式注入防护）；流水只读查看对话框 |

**测试（新增）：**
| 文件 | 说明 |
|------|------|
| `tests/test_transactions_page.py` | 48 个测试：金额格式化、公式注入防护、TableModel 数据/颜色/对齐/锁定状态、EditDialog 构建/验证、TransactionRepository 筛选/排序/分页/稳定排序、CSV 导出、页面构造/控件/菜单验证 |

### 功能实现

**筛选与排序：**
- 日期范围筛选（QDateEdit，支持"全部"）
- 账户筛选（动态加载所有账户）
- 分类筛选（动态加载所有分类）
- 类型筛选（支出/收入/转账）
- 清算状态筛选（全部/已清算/未清算）
- 关键词搜索（匹配备注或ID）
- 稳定排序：同日按 created_at 次排序，再按 id 第三次排序
- 分页：支持 20/50/100/200 条/页

**新增对话框：**
- 支出/收入/转账三种普通新增
- 金额控件：QLineEdit + QDoubleValidator(0.01, 999999999.99, 2)
- 日期：QDateEdit + CalendarPopup
- 转账：来源+目标两个账户选择（禁止同账户）
- 支出/收入：必须选择对应类型的分类
- 应收借出/收回、余额调整、历史结算不出现在普通新增菜单

**编辑与删除：**
- 锁定流水 + 历史结算流水：只读，标注历史导入
- 编辑：弹出确认对话框后再通过 LedgerService.update_transaction 写入
- 删除：弹出确认对话框（含流水详情）后再通过 LedgerService.delete_transaction 写入
- 写入后自动刷新表格并重算受影响账户余额
- 所有写操作产生 AuditEvent

**导出：**
- 按当前筛选条件导出全部数据为 CSV
- 公式注入防护：对以 =、+、-、@ 开头的文本加 ' 前缀
- 金额始终保留两位小数
- UTF-8 BOM 编码（Excel 友好）

**安全规则遵守：**
- 所有流水写操作通过 LedgerService
- UI 层不直写数据库
- 锁定流水拒绝编辑/删除
- 新增菜单不含股票/证券相关入口
- 没有功能性股票流水入口

### 验收结果
- ✅ `ruff check .` — All checks passed
- ✅ `python -m pytest` — **351 passed**（+48 新增）
- ✅ 新增/编辑/删除余额准确（LedgerService → BalanceService 重算）
- ✅ 同日按创建时间稳定排序（测试验证）
- ✅ 金额永远显示两位小数
- ✅ 导出安全（公式注入防护）
- ✅ 无绕过服务层的 SQL 写账
- ✅ 锁定/历史结算流水只读

### 变更记录更新

| 日期 | 步骤 | 变更说明 |
|------|------|----------|
| 2026-07-04 | 08 | 日常流水 — 筛选/CRUD/导出/公式注入防护 + 48 测试 |

---

## 第 09 步完成详情：离线 ECharts 与仪表盘

### 新增/修改文件

**图表模块（新增）：**
| 文件 | 说明 |
|------|------|
| `src/mym2/charts/__init__.py` | charts 包 |
| `src/mym2/charts/option_builders.py` | ECharts option JSON 构建器：资产负债饼图、月度收支柱状图、净资产趋势折线、分类支出饼图，支持深色/浅色主题 |
| `src/mym2/charts/chart_html.py` | HTML 模板生成器：build_chart_html（完整HTML）、update_chart_js（增量更新），不含任何 CDN 引用 |

**UI 组件（新增）：**
| 文件 | 说明 |
|------|------|
| `src/mym2/ui/widgets/__init__.py` | widgets 包 |
| `src/mym2/ui/widgets/chart_web_view.py` | ChartWebView：QWebEngineView 封装，通过 setHtml(local_html, local_base_url) 加载本地 echarts.min.js；一个视图只初始化一次 ECharts 实例；刷新用 updateChart；resize 调用 myChart.resize() |

**服务层（新增）：**
| 文件 | 说明 |
|------|------|
| `src/mym2/services/report_service.py` | ReportService：仪表盘数据聚合（资产/负债/净资产/应收/当月收支/预算概览/月度趋势/分类明细）；DashboardData + MonthlySnapshot 数据类 |

**UI 页面（修改）：**
| 文件 | 说明 |
|------|------|
| `src/mym2/ui/pages/dashboard_page.py` | 完整仪表盘：6 个概览卡片（净资产/总资产/总负债/应收/本月收入/本月支出）；4 个图表（资产负债饼图、月度收支柱状图、净资产趋势折线、分类支出饼图）；最近 10 条流水表格 |

**资源（新增）：**
| 文件 | 说明 |
|------|------|
| `resources/vendor/echarts.min.js` | ECharts 5.6.0 本地副本（~1MB），离线授权使用 |

**测试（新增）：**
| 文件 | 说明 |
|------|------|
| `tests/test_dashboard_echarts.py` | 42 个测试：option_builders 结构/值/CDN-free、chart_html 模板/嵌入/CDN-free、ChartWebView 构造/信号/缓存更新、ReportService 数据聚合（资产/负债/净资产/收支/趋势/分类/预算）、仪表盘构造/控件/禁止词 |

**修改的文件：**
| 文件 | 说明 |
|------|---
---

## 第 10 步完成详情：预算模块

### 新增/修改文件

**Schema 扩展：**
| 文件 | 说明 |
|------|------|
| `src/mym2/db/ensure_schema.py` | Schema 确保工具 — 幂等添加 budget 扩展列 |

**模型层（修改）：**
| 文件 | 说明 |
|------|------|
| `src/mym2/db/models/budget.py` | BudgetPeriod 添加 is_closed；BudgetLine 添加 type/group/threshold_minor/sort_order |

**DTO 层（修改）：**
| 文件 | 说明 |
|------|------|
| `src/mym2/services/dto.py` | 新增 BudgetLineDTO、CreateBudgetPeriodDTO、CopyBudgetDTO、UpdateBudgetLineDTO |

**仓储层（新增）：**
| 文件 | 说明 |
|------|------|
| `src/mym2/repositories/budget_repo.py` | BudgetRepository：期间 CRUD、明细查询、实际发生额查询（排除 balance_adjustment/historical_investment_settlement/receivable）|

**服务层（新增）：**
| 文件 | 说明 |
|------|------|
| `src/mym2/services/budget_service.py` | BudgetService：创建期间、复制上月、添加/编辑/删除明细行、关闭/重新打开月份 |

**UI 页面（修改）：**
| 文件 | 说明 |
|------|------|
| `src/mym2/ui/pages/budget_page.py` | 完整预算页面：月度切换、新建/复制、明细表（分类/分组/计划/实际/剩余/进度/超支状态）、CRUD 对话框、关闭/重新打开 |

**修改的已有文件：**
| 文件 | 说明 |
|------|------|
| `src/mym2/bootstrap.py` | 集成 `ensure_budget_columns`；修复 session factory 初始化 |
| `src/mym2/repositories/__init__.py` | 导出 BudgetRepository |
| `src/mym2/services/__init__.py` | 导出 BudgetService |
| `src/mym2/importers/legacy_mym/executor.py` | 迁移执行后调用 `ensure_budget_columns` |
| `tests/conftest.py` | 测试数据库创建后调用 `ensure_budget_columns` |

### 功能实现

**预算服务：**
- 按月创建预算期间及明细行（支出/收入分类绑定）
- 复制上月预算（查找最近已有期间，复制所有明细行）
- 添加/编辑/删除预算明细行
- 关闭/重新打开预算期间（关闭后禁止编辑）
- 所有写操作产生 AuditEvent

**预算仓储：**
- 按年月查询期间、列出最近 24 个期间
- 构建 BudgetPeriodView（含 BudgetLineWithActual：计划/实际/剩余/进度/超支状态）
- 实际发生额从 transactions 实时查询，排除：
  - `balance_adjustment`（余额调节）
  - `historical_investment_settlement`（历史投资结算）
  - `receivable_advance` / `receivable_repayment`（应收垫付/还款）
  - `transfer`（转账）
- 不维护第二套"已用金额"事实源

**预算页面：**
- 月度切换导航（上月/下月按钮 + 年月标签）
- 新建预算对话框（支出/收入双选项卡，按分类填写金额）
- 复制上月按钮
- 预算明细表：分类、类型、分组、计划金额、实际金额、剩余、进度百分比、超支/正常/已达状态
- 汇总行：计划总计、实际总计、剩余、项数
- 超支行/已达行高亮（红色/绿色背景）
- 添加/编辑/删除明细行对话框
- 关闭月份（确认后禁止编辑）/ 重新打开
- 暂不实现 AI 预算建议（留有明确扩展接口）

**安全规则遵守：**
- 所有预算写操作通过 BudgetService
- UI 层不直写 budget_periods / budget_lines
- 关闭月份拒绝编辑/删除
- 实际发生额不维护冗余事实源

### 验收结果
- ✅ `ruff check .` — All checks passed
- ✅ `python -m pytest` — **393 passed**（所有已有测试通过）
- ✅ 预算实际额从 transactions 实时查询（排除调节/结算/应收类型）
- ✅ 关闭月不可编辑（服务层 + UI 层双重保护）
- ✅ 复制预算不重复（检查目标期间是否已存在）
- ✅ 历史快照/估值调整不污染日常预算

### 变更记录更新

| 日期 | 步骤 | 变更说明 |
|------|------|----------|
| 2026-07-04 | 10 | 预算模块 — BudgetService + BudgetRepository + BudgetPage + schema 扩展 |

---|
| `src/mym2/services/__init__.py` | 导出 ReportService |
| `pyproject.toml` | 添加 mym2.charts、mym2.ui.widgets 包 |

### 功能实现

**图表组件：**
- QWebEngineView + 本地 echarts.min.js（setHtml + base_url）
- 生成的 HTML/JS 不含 http://、https://、CDN 域名
- 一个视图只初始化一次 ECharts 实例
- 刷新数据用 setOption + runJavaScript（不重新加载 HTML）
- 窗口 resize 自动调用 chart.resize()
- 深色主题：文字/轴/提示框可读（已验证）

**仪表盘：**
- 概览卡片：净资产、总资产、总负债、应收款、本月收入、本月支出
- 图表：资产负债构成（双饼图）、月度收支（柱状图）、净资产趋势（面积折线图）、当月分类支出（饼图）
- 最近 10 条流水明细
- 投资历史资产快照计入资产总额但不展示股票名称、行情、价格走势或交易信息
- 数据聚合通过 ReportService（只读）；口径与后续 ReportService 约定一致

**安全规则遵守：**
- 图表全部本地离线，无外网依赖
- 无 CDN 引用（HTML/JS 静态检查通过）
- 仪表盘不含股票/证券相关入口或展示词
- 数据聚合只读，不直写数据库

### 验收结果
- ✅ `ruff check .` — All checks passed
- ✅ `python -m pytest` — **393 passed**（+42 新增）
- ✅ HTML/JS 静态检查：不含 http://、https://、CDN 域名
- ✅ QWebEngineView setHtml + local_base_url 加载 echarts.min.js
- ✅ 仪表盘口径与 ReportService 约定一致
- ✅ 无外网依赖；投资快照不泄露股票信息

### 变更记录更新

| 日期 | 步骤 | 变更说明 |
|------|------|----------|
| 2026-07-04 | 09 | 离线 ECharts 与仪表盘 — ChartWebView + option_builders + ReportService + 42 测试 |
