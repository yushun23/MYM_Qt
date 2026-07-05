# 旧系统模块关系图（Legacy Module Map）

> 依据：旧项目 Flet 源码结构。本图展示旧系统 UI 层 → 服务层 → 数据层的调用关系。

## 模块关系图

```mermaid
graph TB
    subgraph "UI 层 (Flet Pages)"
        MAIN[main.py<br/>应用入口/Flet App]
        DASHBOARD[view_dashboard.py<br/>仪表盘]
        RECORD[view_record.py<br/>收支记录]
        ACCOUNTS[view_accounts.py<br/>账户与分类]
        RECEIVABLE[view_receivable.py<br/>应收账款]
        BUDGET[view_budget.py<br/>月度预算]
        REPORT[view_report.py<br/>收支/资产负债表]
        STOCK[view_stock*.py<br/>股票/投资]
        AI[view_ai.py<br/>AI助手]
        SETTINGS[view_settings.py<br/>设置中心]
    end

    subgraph "服务层"
        TX_SVC[transaction_service.py<br/>交易写入/修改/删除]
        AI_SVC[ai_service.py<br/>AI聊天与动作]
        CHART_SVC[pyecharts_chart_service.py<br/>图表生成]
        STOCK_SVC[stock_*.py<br/>股票行情/月结/导入]
        PLUGIN[plugin_loader.py<br/>插件加载]
    end

    subgraph "数据/基础设施层"
        DB[database.py<br/>SQLite连接/建表]
        MIG[migrations.py<br/>Schema迁移]
        TX_TYPES[transaction_types.py<br/>交易类型定义]
        PATHS[app_paths.py<br/>应用路径]
        I18N[i18n_manager.py<br/>多语言]
        THEME[mym_theme.py<br/>主题颜色]
    end

    subgraph "外部"
        SQLITE[(SQLite<br/>.mym文件)]
    end

    MAIN --> DB
    MAIN --> PATHS
    MAIN --> MIG
    
    DASHBOARD --> DB
    RECORD --> TX_SVC
    RECORD --> DB
    ACCOUNTS --> DB
    RECEIVABLE --> TX_SVC
    RECEIVABLE --> DB
    BUDGET --> DB
    REPORT --> CHART_SVC
    REPORT --> DB
    STOCK --> STOCK_SVC
    STOCK --> TX_SVC
    STOCK --> DB
    AI --> AI_SVC
    AI --> TX_SVC
    SETTINGS --> DB
    SETTINGS --> I18N
    SETTINGS --> THEME
    
    TX_SVC --> DB
    TX_SVC --> TX_TYPES
    AI_SVC --> DB
    CHART_SVC --> DB
    STOCK_SVC --> DB
    PLUGIN --> DB
    
    DB --> SQLITE
```

## 关键调用路径

### 1. 记一笔（核心路径）
```
view_record.py → transaction_service.py → database.py → SQLite
```

### 2. 仪表盘查询
```
view_dashboard.py → database.py (直接SQL查询) → SQLite
```

### 3. 报表生成
```
view_report.py → pyecharts_chart_service.py → database.py → SQLite
```

### 4. AI 记账
```
view_ai.py → ai_service.py → transaction_service.py → database.py → SQLite
```

### 5. 股票月结
```
view_stock*.py → stock_*.py → transaction_service.py → database.py → SQLite
```

### 6. 应收账款
```
view_receivable.py → transaction_service.py → database.py → SQLite
```

## 旧系统关键风险点

| 风险点 | 涉及文件 | 描述 |
|---|---|---|
| UI 直写 SQL | `view_dashboard.py`, `view_accounts.py`, `view_budget.py` | 多个页面绕过服务层直接执行SQL查询 |
| 跨线程 SQLite | `stock_*.py`, `ai_service.py` | 后台线程共享数据库连接 |
| 浮点金额 | 多处 | 部分金额计算使用float而非Decimal |
| 破坏性 Migration | `migrations.py` | 直接在旧.mym上ALTER TABLE |
| 股票重复统计 | `view_dashboard.py` | 股票联动账户可能被重复计入总资产 |

---

## 关键旧代码引用

### 数据库连接（database.py）
- `get_db()` - 获取数据库连接
- `init_db()` - 初始化数据库表
- `get_db_path()` - 获取数据库路径

### 交易服务（transaction_service.py）
- `add_transaction()` - 添加交易
- `update_transaction()` - 更新交易
- `delete_transaction()` - 删除交易
- `recalculate_balances()` - 余额重算

### 交易类型（transaction_types.py）
- `TransactionType` 枚举 - 收入/支出/转账/垫付/收回/余额调整/股票月结等

### 迁移（migrations.py）
- `migrate_database()` - 执行迁移
- `check_schema_version()` - 检查版本
