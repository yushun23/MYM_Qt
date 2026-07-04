# MYM2 数据迁移方案（DATA MIGRATION）

> 版本：1.0.0 | 最后更新：2026-07-04

---

## 1. 旧系统概况

| 项目 | 详情 |
|------|------|
| 技术栈 | Python + Flet + SQLite |
| 数据库文件 | `.mym` 扩展名（实际为 SQLite 格式） |
| 金额存储 | SQLite `REAL` 类型（浮点） |
| 约定路径 | `legacy_input/my_money.mym` |
| 约定源码 | `legacy_input/MYM-main/` |

---

## 2. 已知旧库表结构

### 2.1 核心业务表（优先迁移）

| 旧表 | 说明 | 迁移策略 |
|------|------|----------|
| `accounts` | 账户 | 迁移到新 `accounts`，金额 REAL → INTEGER 分 |
| `categories` | 分类 | 迁移到新 `categories` |
| `transactions` | 流水 | 迁移到新 `transactions`，金额 REAL → INTEGER 分 |

### 2.2 预算表（优先迁移）

| 旧表 | 说明 | 迁移策略 |
|------|------|----------|
| `budget_months` | 预算月份 | 映射到新 `budget_periods` |
| `budget_items` | 预算项目定义 | 映射到新预算结构 |
| `budget_lines` | 预算明细行 | 迁移到新 `budget_lines` |

### 2.3 股票相关表（仅归档）

| 旧表 | 说明 | 迁移策略 |
|------|------|----------|
| `stock_accounts` | 证券账户关联 | → `legacy_archive_records` |
| `stock_cash_flows` | 资金流水 | → `legacy_archive_records` |
| `stock_module_meta` | 模块元数据 | → `legacy_archive_records` |
| `stock_monthly_settlements` | 月度结算 | → `legacy_archive_records` |
| `stock_quotes` | 行情数据 | → `legacy_archive_records` |
| `stock_settlement_imports` | 结算导入 | → `legacy_archive_records` |
| `stock_symbols` | 股票代码 | → `legacy_archive_records` |
| `stock_trades` | 交易记录 | → `legacy_archive_records` |

### 2.4 辅助表（选择性处理）

| 旧表 | 说明 | 迁移策略 |
|------|------|----------|
| `settings` | 设置 | **白名单导入**：仅主题偏好等；API key、密码、password_hash **跳过** |
| `ai_chat_messages` | AI 对话 | → `legacy_archive_records`（仅归档，不作为新 AI 上下文） |
| `ai_imported_records` | AI 导入记录 | → `legacy_archive_records` |
| `schema_migrations` | 旧迁移记录 | **跳过**（Alembic 是新版本来源） |

---

## 3. 金额转换规则

1. 旧库金额为 `REAL`（例如 `123.45` 表示 123.45 元）。
2. 转换为整数分：`int(round(real_amount * 100))`。
3. 转换后验证：源 REAL 值 × 100 与目标 INTEGER 分差值不超过 ±1 分（容忍浮点舍入误差）。
4. 转换失败的记录写入警告列表，不静默丢弃。

---

## 4. 链接证券账户处理

旧系统中存在链接证券账户（如"广发证券"），其余额由股票持仓估值逻辑计算，**不能仅由普通流水重算**。

### 处理策略

1. 识别链接证券账户（通过 `stock_accounts` 表关联或命名规则）。
2. 为每个链接证券账户创建一个不可编辑的 **历史投资资产快照** 账户：
   - `type = "investment_snapshot"`
   - `is_editable = False`
   - `balance = 旧账户余额（转换后整数分）`
3. 如普通流水重算余额 ≠ 旧账户余额，创建一条不可编辑的 **历史估值调节记录**（`historical_investment_settlement` 类型流水），补齐差额。
4. 所有股票相关原始数据归档到 `legacy_archive_records`。

### 核对目标

迁移后 `Σ 所有账户余额（含快照账户）` 应与旧系统净资产一致，允许 ±5 分的舍入误差。

---

## 5. 敏感数据过滤

### 旧 `settings` 白名单

| 允许导入 | 说明 |
|----------|------|
| `theme` | 主题偏好 |
| `language` | 语言设置 |
| `currency_display` | 货币显示偏好 |

### 强制跳过

| 跳过字段 | 原因 |
|----------|------|
| `api_key` | 密钥 |
| `proxy_password` | 代理密码 |
| `password_hash` | 密码哈希 |
| `openai_api_key` | API 密钥 |
| 任何含 `token`/`secret`/`password`/`key` 的字段 | 安全 |

---

## 6. 迁移流程

```
1. 预检查（pre_check）
   ├── 验证旧 .mym 可打开且为有效 SQLite
   ├── 检查必需表是否存在
   ├── 统计各表行数
   └── 输出预检查报告

2. Dry‑Run（dry_run）
   ├── 在新临时数据库中执行全部迁移
   ├── 验证新库完整性
   ├── 计算净资产核对
   └── 输出 Dry‑Run 报告（含警告和错误）

3. 用户确认
   └── 显示报告，等待用户确认

4. 正式迁移（migrate）
   ├── 开启事务
   ├── 执行全部迁移步骤
   ├── 写入 LegacyIdMap
   ├── 写入 ImportRun 记录
   ├── 如失败 → 完整回滚
   └── 输出最终报告

5. 重复导入防护
   └── 检查 ImportRun 记录，拒绝重复导入同一旧库
```

---

## 7. 错误处理

| 场景 | 处理 |
|------|------|
| 旧库文件不存在 | 提示用户放置文件到 `legacy_input/` |
| 旧库表结构不匹配 | 报错并列出缺失/多余的表 |
| 单行转换失败 | 跳过该行，记录警告，继续迁移其他行 |
| 事务中任意步骤失败 | 完整回滚，输出失败原因 |

---

## 8. 依赖

- 旧 `.mym` 必须存在于 `legacy_input/my_money.mym`。
- 旧源码放置于 `legacy_input/MYM-main/` 供参考，非运行时依赖。
- 缺失旧文件时迁移功能不得猜测表结构，只报告缺失。

---

> 具体迁移实现见第 13 步。迁移前务必阅读本文档与 `PROJECT_CONTRACT.md`。
