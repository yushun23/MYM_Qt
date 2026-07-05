# MYM - Manage Your Money

本地桌面记账软件（新架构 PySide6 重建版）。

## 开发环境

- Python 3.12+
- 虚拟环境：`python -m venv .venv && source .venv/bin/activate`

## 安装依赖

```bash
pip install -e ".[dev]"
```

## 启动

```bash
python -m mym
```

## 测试

```bash
# 冒烟测试
pytest tests/test_smoke.py -v

# 全部测试
pytest -v
```

## 技术栈

- **UI**: PySide6 Widgets
- **ORM**: SQLAlchemy 2.x
- **数据库**: SQLite
- **迁移**: Alembic
- **图表**: QWebEngineView + 本地 ECharts
- **测试**: pytest + pytest-qt

## 项目结构

```
src/mym/
├── ui/              # 表现层
├── application/     # 应用层（Use Cases/Services）
├── domain/          # 领域层（实体/枚举/规则）
└── infrastructure/  # 基础设施层（DB/路径/日志）
```
