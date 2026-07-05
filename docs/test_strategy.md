# MYM 测试策略

## 测试分类

### 单元测试 (`tests/unit/`)
- 测试单个类/函数，不依赖数据库或UI
- 使用 mock 隔离外部依赖
- 快速执行，适合开发中频繁运行

### 集成测试 (`tests/`)
- 测试服务层与数据库交互
- 使用内存 SQLite 数据库
- 包含账务、应收、预算、股票、AI、导入、迁移

### UI 测试 (pytest-qt)
- 测试 PySide6 窗口和组件
- 包含主窗口导航、记账表单、迁移向导

### 迁移一致性测试
- 新旧库按账户余额、交易数、月收入、月支出对账

## 测试命令

```bash
# 快速冒烟测试
pytest tests/test_smoke.py -v

# 全量测试
pytest tests/ -v

# 按模块测试
pytest tests/test_p5_ledger_service.py -v          # 核心账务
pytest tests/test_p18_receivable.py -v             # 应收
pytest tests/test_p19_budget.py -v                 # 预算
pytest tests/test_p22_investment.py -v             # 股票
pytest tests/test_p29_p30_ai.py -v                 # AI
pytest tests/test_p31_ai_analysis.py -v            # AI分析
pytest tests/test_p32_attachment.py -v             # 附件分析
pytest tests/test_p33_import.py -v                 # 表格导入
pytest tests/test_p34_p36_migration.py -v          # 旧库迁移

# 覆盖率
pytest tests/ --cov=src/mym --cov-report=html
```

## Fixtures

- `new_ledger` - 空白新账本
- `populated_session` - 含完整业务数据的 Session
- `old_db_path` - 模拟旧 .mym 文件

## 回归门禁

每次代码修改必须通过以下测试：
1. `test_p5_ledger_service.py` - 核心账务不被破坏
2. `test_p34_p36_migration.py` - 旧库迁移正常
3. `test_p31_ai_analysis.py` - AI 分析数据正确

## 覆盖率目标

- `application/services` - 80%+
- `domain/entities` - 70%+
- `infrastructure/migrations` - 80%+
