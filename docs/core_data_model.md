# 核心数据模型（Core Data Model）

## ER 图

```mermaid
erDiagram
    Account ||--o{ TransactionLine : "transaction_lines.account_id"
    Category ||--o{ TransactionLine : "transaction_lines.category_id"
    Transaction ||--o{ TransactionLine : "transaction_lines.transaction_id"
    ImportJob ||--o{ Transaction : "transactions.import_job_id"
    ImportJob ||--o{ ImportIssue : "import_issues.import_job_id"
    ImportJob ||--o{ LegacyIdMap : "legacy_id_map.import_job_id"

    Account {
        int id PK
        string name "唯一"
        string account_type "asset|liability|receivable|investment_linked"
        string currency "CNY"
        string group_name
        decimal opening_balance "Numeric(18,2)"
        decimal current_balance "Numeric(18,2) 缓存，可重算"
        bool is_enabled
        bool is_system_locked
        bool is_archived
        bool is_deleted "软删除"
        string notes
        datetime created_at
        datetime updated_at
    }

    Category {
        int id PK
        string name
        string category_type "income|expense|system"
        string group_name
        bool is_enabled
        bool is_system_locked
        bool include_in_reports
        int sort_order
        bool is_deleted
        string notes
        datetime created_at
        datetime updated_at
    }

    Transaction {
        int id PK
        string business_type "income|expense|transfer|lend|recover|balance_adjustment|stock_profit|stock_loss"
        date transaction_date
        string description
        string source "manual|import|migration|ai|system"
        string status "draft|posted|void"
        int import_job_id FK
        bool is_cleared
        datetime created_at
        datetime updated_at
    }

    TransactionLine {
        int id PK
        int transaction_id FK
        int account_id FK
        int category_id FK "可为null（转账行不需要）"
        string role "debit|credit"
        decimal signed_amount "Numeric(18,2)"
        string memo
        int sort_order
    }

    ImportJob {
        int id PK
        string source_file
        string file_hash "SHA256"
        string import_type
        string status "pending|previewing|in_progress|completed|failed|rolled_back"
        int total_rows
        int success_rows
        int skipped_rows
        int error_rows
        string summary
        datetime created_at
        datetime updated_at
    }

    ImportIssue {
        int id PK
        int import_job_id FK
        int row_number
        string severity "info|warning|error"
        string message
        string raw_data
    }

    LegacyIdMap {
        int id PK
        int import_job_id FK
        string legacy_table
        string legacy_pk
        string new_table
        string new_id
    }

    AuditLog {
        int id PK
        string action "create|update|void|delete|import|archive"
        string entity_type
        string entity_id
        string summary_before
        string summary_after
        string source
        string operator
        datetime created_at
        datetime updated_at
    }

    AppSetting {
        int id PK
        string key "唯一"
        string value
        string description
        datetime created_at
        datetime updated_at
    }
```

## 交易行配对规则（金额守恒）

每种业务类型的 TransactionLine 必须满足 `SUM(signed_amount) = 0`：

| 业务类型 | 行1 (debit) | 行2 (credit) | 说明 |
|---|---|---|---|
| income | 资产账户 +amount | 收入分类 -amount | 收入 |
| expense | 支出分类 +amount | 资产账户 -amount | 支出 |
| transfer | 转入账户 +amount | 转出账户 -amount | 转账 |
| lend | 应收账户 +amount | 资产账户 -amount | 垫付 |
| recover | 资产账户 +amount | 应收账户 -amount | 收回 |
| balance_adjustment | 目标账户 ±amount | 系统分类 ∓amount | 余额调整 |
| stock_profit | 资产账户 +amount | 收入分类 -amount | 股票盈利 |
| stock_loss | 支出分类 +amount | 资产账户 -amount | 股票亏损 |

## 字段约束

- `signed_amount`：必填，Decimal，精度18位，小数2位
- `transaction_date`：必填，不能是未来日期
- `account_id`：必填，账户必须存在且启用
- `category_id`：转账行可为null，收入/支出/应收/调整必须有有效分类
- 资产账户的 signed_amount: debit为正表示增加，credit为正表示减少
- 同账户不可互转
- 普通记账的账户不能是 receivable 或 investment_linked 类型

## 索引

- `accounts.name` UNIQUE
- `categories(name, category_type)` UNIQUE
- `app_settings.key` UNIQUE
- `transactions.transaction_date` INDEX
- `transactions.status` INDEX
- `transaction_lines.transaction_id` INDEX (FK)
- `transaction_lines.account_id` INDEX
- `transaction_lines.category_id` INDEX
