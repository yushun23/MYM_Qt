# MYM 功能对等矩阵（Feature Parity Matrix）

> 依据：旧项目源码 `main.py`、`database.py`、`migrations.py`、`transaction_service.py`、`transaction_types.py`、`view_*.py`、`stock_*.py`、`ai_service.py`、`plugin_loader.py` 等。
> 目的：确保新架构不遗漏任何旧功能，并明确新旧映射关系。

## 旧模块 → 新架构映射

| 旧模块/文件 | 旧功能 | 新架构对应域 | 状态 |
|---|---|---|---|
| `main.py` | 应用入口、Flet app 创建 | `mym/app.py` QApplication 入口 | 待实现 |
| `database.py` | SQLite 连接、建表、Schema 管理 | `mym/infrastructure/database.py` SQLAlchemy Engine + Alembic | 待实现 |
| `app_paths.py` | 用户数据目录、账本目录、备份/导出目录 | `mym/infrastructure/paths.py` 路径服务 | 待实现 |
| `migrations.py` | Schema 版本、补列、余额重算 | `mym/infrastructure/migrations/` Alembic | 待实现 |
| `transaction_service.py` | 统一写入、修改、删除、余额重算 | `mym/application/services/ledger_service.py` | 待实现 |
| `transaction_types.py` | 交易类型定义与兼容映射 | `mym/domain/enums.py` | 待实现 |
| `view_dashboard.py` | 资产/负债/净资产、应收、预算、趋势、最近流水 | `mym/ui/pages/dashboard_page.py` | 待实现 |
| `view_record.py` | 收支记录、筛选、编辑、删除 | `mym/ui/pages/record_page.py` | 待实现 |
| `view_accounts.py` | 账户列表、分类管理、账户详情流水、CSV导出 | `mym/ui/pages/accounts_page.py` | 待实现 |
| `view_receivable.py` | 垫付/借出、收回欠款、批量核销、未回收报表、期初CSV导入 | `mym/ui/pages/receivable_page.py` + `mym/domain/receivable/` | 待实现 |
| `view_budget.py` | 月度预算、收支预算树、实际值、快照、复制、关闭/重开、AI建议 | `mym/ui/pages/budget_page.py` + `mym/domain/budget/` | 待实现 |
| `view_report.py` | 收支报表、资产负债表、图表、HTML打印预览 | `mym/ui/pages/report_page.py` | 待实现 |
| `pyecharts_chart_service.py` | pyecharts图表生成 | `mym/infrastructure/chart_service.py` + ChartHost | 待实现 |
| `view_stock*.py` | 股票账户、资金池、买卖股息、持仓 | `mym/ui/pages/stock_page.py` + `mym/domain/investment/` | 待实现 |
| `stock_*.py` | 行情、交易复盘、券商结算单导入、月度结算 | `mym/application/services/investment_service.py` | 待实现 |
| `view_ai.py`、`ai_service.py`、`ai_action_spec.py` | AI聊天、查询分析、AI记账、改删流水、应收操作、附件分析、AI导入 | `mym/ui/pages/ai_page.py` + `mym/application/services/ai_service.py` | 待实现 |
| `view_settings.py` | 语言、主题、字体、壁纸、密码、数据、代理、AI设置 | `mym/ui/pages/settings_page.py` | 待实现 |
| `i18n_manager.py` | 多语言管理 | `mym/infrastructure/i18n.py` | 待实现 |
| `mym_theme.py` | 主题颜色定义 | `mym/ui/theme.py` | 待实现 |
| `plugin_loader.py` | 插件加载与功能开关 | `mym/infrastructure/plugin_manager.py` | 待实现 |

## 功能完整性检查清单

### 应用启动与生命周期
- [ ] 创建本地账套（SQLite文件）
- [ ] 打开已有账套
- [ ] 账套密码设置与验证
- [ ] 最近账套列表
- [ ] 用户数据目录管理
- [ ] 异常日志捕获与记录
- [ ] 自动备份策略

### 核心账务
- [ ] 记收入
- [ ] 记支出
- [ ] 记转账
- [ ] 编辑交易
- [ ] 删除/作废交易
- [ ] 余额重算
- [ ] 统一写入服务（所有入口共用）
- [ ] 审计日志

### 账户与分类
- [ ] 账户新增/编辑/归档
- [ ] 账户类型：资产、负债、应收、投资联动
- [ ] 分类新增/编辑/启停
- [ ] 系统分类保护
- [ ] 账户详情与流水
- [ ] CSV导出

### 仪表盘
- [ ] 总资产/总负债/净资产
- [ ] 应收余额
- [ ] 预算执行率
- [ ] 近6个月趋势
- [ ] 最近流水

### 报表
- [ ] 收支报表（期间、分类、趋势）
- [ ] 资产负债表
- [ ] 图表（柱状图、饼图、折线图）
- [ ] 钻取（点击图表跳转流水）
- [ ] PNG/PDF/CSV/XLSX导出
- [ ] 打印预览

### 应收账款
- [ ] 垫付/借出
- [ ] 收回欠款
- [ ] 批量核销
- [ ] 未回收报表
- [ ] 期初CSV导入
- [ ] 折损/坏账处理

### 预算
- [ ] 月度预算创建
- [ ] 收入/支出预算树
- [ ] 实际值自动计算
- [ ] 预算快照（关闭月份保留）
- [ ] 从上月复制
- [ ] 关闭/重新打开月份
- [ ] 超支提醒
- [ ] AI建议

### 股票/投资
- [ ] 股票账户管理
- [ ] 资金池（转入/转出/调整）
- [ ] 买入/卖出/股息
- [ ] 持仓计算
- [ ] 行情服务（在线/离线缓存）
- [ ] 交易复盘
- [ ] 券商结算单导入（CSV/XLSX/XLS）
- [ ] 月度结算（盈利/亏损入普通账本）
- [ ] 模块隐藏/归档
- [ ] 按导入批次回滚
- [ ] 永久删除前备份与确认

### AI助手
- [ ] AI聊天（多provider支持）
- [ ] 查询分析（月度收支、异常等）
- [ ] AI记账（需用户确认）
- [ ] 修改/删除流水（需用户确认）
- [ ] 应收操作（需用户确认）
- [ ] 附件分析（TXT/CSV/XLSX/DOCX/PDF/图片）
- [ ] AI导入（表格流水识别）
- [ ] 可视化Canvas
- [ ] 风险等级与审批工作流

### 设置
- [ ] 语言切换（zh-CN/en）
- [ ] 主题切换（light/dark/system）
- [ ] 字体设置
- [ ] 壁纸
- [ ] 密码修改
- [ ] 网络代理
- [ ] AI配置
- [ ] 股票模块开关
- [ ] 插件启用/禁用

### 插件
- [ ] 插件发现与加载
- [ ] 启用/禁用
- [ ] 加载错误隔离
- [ ] 权限控制
- [ ] 示例插件

### 数据迁移
- [ ] 旧.mym扫描
- [ ] 迁移预检查
- [ ] 账户迁移
- [ ] 分类迁移
- [ ] 普通流水迁移
- [ ] 应收迁移
- [ ] 预算迁移
- [ ] 股票迁移
- [ ] AI历史迁移
- [ ] 迁移报告
- [ ] 迁移向导UI
- [ ] 回滚

### 备份与安全
- [ ] 自动备份
- [ ] 手动备份
- [ ] 从备份恢复
- [ ] 数据库健康检查
- [ ] 密码保护
- [ ] API Key安全存储
- [ ] 日志脱敏

---

**P0 验收清单：**
- [x] 功能矩阵覆盖旧项目所有主要页面和服务
- [x] 股票、AI、应收、预算等"大功能"不遗漏
- [x] 每个旧模块都有明确的新架构对应域
- [x] 功能清单可指导后续P1-P42开发
