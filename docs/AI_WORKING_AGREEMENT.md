# AI 工作协议（AI Working Agreement）

> 本文件定义了 AI 编程助手在 MYM 新架构中必须持续遵守的全局工程约束。
> 后续每一个 P# 步骤均视为已加载本协议。

---

## 你正在重建 MYM（Manage Your Money）本地桌面记账软件

### 固定技术栈

- Python 3.12
- PySide6 Widgets，不使用 Flet
- SQLAlchemy 2.x + SQLite
- QWebEngineView + QWebChannel + 本地 ECharts；pyecharts 仅用于标准图快速生成
- pytest + pytest-qt
- 不依赖云端后端；账本默认是用户本地 SQLite 文件

### 架构边界

1. UI 层不得直接执行 SQL、不得直接写数据库。
2. 所有业务写入都必须经 application/use_cases 或 application/services。
3. 所有数据库访问必须经 repository / SQLAlchemy Session。
4. 每个线程、每个后台任务创建独立短生命周期 Session；禁止跨线程共享 Session 或 SQLite 连接。
5. 所有资金相关写入必须在一个数据库事务中完成，并写入审计日志。
6. 数据库中的金额统一使用 Decimal / Numeric(18,2) 语义；禁止用 float 作为业务金额计算。
7. 账户余额是可重算缓存：必须能由 opening_balance + 已过账交易重新得到。
8. 普通流水、AI 写账、CSV/Excel 导入、应收核销、股票月结都必须走同一套核心账务写入服务。
9. 旧 `.mym` 账本只能只读扫描、备份、迁移；绝不在旧账本上直接做破坏性 schema 改造。
10. 股票联动账户、应收账户不得出现在普通"记一笔"的可选账户列表中。
11. 股票模块必须可隐藏、归档、按导入批次撤销，且在明确确认和备份后才允许物理删除。
12. 不得把 API Key、账套密码、真实本地绝对路径、完整用户账务内容写入日志、测试快照或文档。
13. HTML/图表中显示的用户输入必须在 Python 端转义；生产环境不能依赖 CDN。
14. 不要一次重写整个项目。每一步只处理本提示词要求的范围，输出完整改动清单、测试和运行方法。

### 代码规范

- 使用明确类型注解
- 使用 `logging.getLogger(__name__)` 获取日志器
- 使用 pathlib.Path 处理文件路径
- 所有金额使用 Decimal 类型
- 使用 Pydantic 进行 DTO 序列化和验证
- 每个公共函数/方法有 docstring
- 遵循 src/mym 目录分层约定

### 输出格式

每次完成一个 P# 步骤后，按以下格式答复合规：
1. 本步目标与边界
2. 读取了哪些现有文件
3. 新增/修改文件清单
4. 完整代码（仅本步相关）
5. 数据库 migration 说明（如有）
6. 自动化测试及结果
7. 人工验收步骤
8. 已知限制 / 下一步前置条件
9. 不应被改动的旧功能或数据保护说明
