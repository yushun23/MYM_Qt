# MYM2 开发进度

> 最后更新：2026-07-04

---

## 里程碑进度

| 步骤 | 内容 | 状态 | 完成日期 | Git Commit |
|------|------|------|----------|------------|
| 00 | 工程基线 | ✅ 完成 | 2026-07-04 | `0084fd1` |
| 01 | 最小可启动 GUI | ✅ 完成 | 2026-07-04 | 待提交 |
| 02 | 数据库基础 | ⏳ 待开始 | — | — |
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

## 第 01 步完成详情

### 新增文件（11 个）

| 文件 | 说明 |
|------|------|
| `src/mym2/core/__init__.py` | core 包 |
| `src/mym2/core/paths.py` | 用户数据路径管理（QStandardPaths + 覆写） |
| `src/mym2/core/logging.py` | 统一日志配置 + 未捕获异常 hook |
| `src/mym2/ui/__init__.py` | ui 包 |
| `src/mym2/ui/main_window.py` | QMainWindow + 左侧导航 + QStackedWidget |
| `src/mym2/ui/pages/__init__.py` | pages 包 |
| `src/mym2/ui/pages/dashboard_page.py` | 仪表盘占位页 |
| `src/mym2/ui/pages/transactions_page.py` | 流水占位页 |
| `src/mym2/ui/pages/accounts_page.py` | 账户占位页 |
| `src/mym2/ui/pages/receivables_page.py` | 应收占位页 |
| `src/mym2/ui/pages/budget_page.py` | 预算占位页 |
| `src/mym2/ui/pages/reports_page.py` | 报表占位页 |
| `src/mym2/ui/pages/settings_page.py` | 设置占位页 |
| `src/mym2/bootstrap.py` | 应用启动引导（QApplication + 日志 + 样式） |
| `src/mym2/app.py` | 入口（支持 --dev 模式） |
| `tests/conftest.py` | pytest-qt offscreen 配置 |
| `tests/test_app_startup.py` | 启动测试（7 个用例） |

### 验收结果
- ✅ `python -m compileall src` — 全部通过
- ✅ `ruff check .` — All checks passed
- ✅ `python -m pytest` — 32 passed
- ✅ 导航栏 7 项（仪表盘/流水/账户/应收/预算/报表/设置），无股票
- ✅ 无 Flet 依赖
- ✅ 窗口创建/切换/关闭不抛异常
- ✅ 用户数据路径不落项目目录

---

## 变更记录

| 日期 | 步骤 | 变更说明 |
|------|------|----------|
| 2026-07-04 | 00 | 建立工程基线 — 13 个文件 |
| 2026-07-04 | 01 | 可启动 GUI 空壳 — 16 个文件，32 测试 |
