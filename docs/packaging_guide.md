# MYM 打包与部署指南

## 支持平台
- macOS 12+
- Windows 10/11
- Linux (Ubuntu 22.04+)

## 打包工具

### 方式一：pyside6-deploy（推荐）
```bash
# 安装
pip install pyside6-deploy

# 打包
pyside6-deploy src/mym/app.py --name MYM

# 包含资源
pyside6-deploy src/mym/app.py --name MYM \
  --extra-packages openpyxl,pandas,SQLAlchemy,alembic \
  --extra-data src/mym/resources:resources
```

### 方式二：PyInstaller（兜底）
```bash
pip install pyinstaller

pyinstaller --name MYM \
  --windowed \
  --add-data "src/mym/resources:resources" \
  --hidden-import openpyxl \
  --hidden-import pandas \
  src/mym/app.py
```

## 资源打包清单
- `src/mym/resources/i18n/` - 翻译文件
- `src/mym/resources/echarts.min.js` - 本地 ECharts
- `src/mym/resources/html/` - HTML 模板
- 应用图标（.ico / .icns / .png）

## 版本管理
- 应用版本：`pyproject.toml` 中 `version`
- 数据库 schema version：Alembic migration head
- 升级兼容策略：启动时检查版本号，必要时自动备份后升级

## 升级流程
1. 启动时检查 `app_version` 与上次运行时版本
2. 检查数据库 schema version
3. 如需升级：自动备份当前数据库
4. 执行 Alembic migration
5. 失败可恢复旧备份

## 诊断包
- 生成脱敏诊断信息（不含真实账本数据、API key、密码）
- 包含：应用版本、OS 版本、日志摘要、schema version

## 注意事项
- 不把用户真实账本样本打进发布包
- 不使用只在开发机运行的相对路径
- QWebEngine 资源使用 `file://` 本地路径
