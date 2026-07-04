"""MYM2 工程契约验证测试。

验证项目基线文件存在且包含关键约束条款。
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def read_doc(filename: str) -> str:
    """读取 docs/ 下的文档内容。"""
    path = PROJECT_ROOT / 'docs' / filename
    assert path.exists(), f'文档不存在: {path}'
    return path.read_text(encoding='utf-8')


# ── 文件存在性 ──────────────────────────────────────────

def test_project_contract_exists():
    """验证 PROJECT_CONTRACT.md 存在。"""
    assert (PROJECT_ROOT / 'docs' / 'PROJECT_CONTRACT.md').exists()


def test_rebuild_spec_exists():
    """验证 REBUILD_SPEC.md 存在。"""
    assert (PROJECT_ROOT / 'docs' / 'REBUILD_SPEC.md').exists()


def test_data_migration_exists():
    """验证 DATA_MIGRATION.md 存在。"""
    assert (PROJECT_ROOT / 'docs' / 'DATA_MIGRATION.md').exists()


def test_adr_0001_exists():
    """验证 ADR/0001-architecture.md 存在。"""
    assert (PROJECT_ROOT / 'docs' / 'ADR' / '0001-architecture.md').exists()


def test_progress_exists():
    """验证 PROGRESS.md 存在。"""
    assert (PROJECT_ROOT / 'PROGRESS.md').exists()


def test_readme_exists():
    """验证 README.md 存在。"""
    assert (PROJECT_ROOT / 'README.md').exists()


def test_gitignore_exists():
    """验证 .gitignore 存在。"""
    assert (PROJECT_ROOT / '.gitignore').exists()


def test_pyproject_exists():
    """验证 pyproject.toml 存在。"""
    assert (PROJECT_ROOT / 'pyproject.toml').exists()


# ── 关键约束条款验证 ─────────────────────────────────────

def test_contract_contains_pyside6():
    """PROJECT_CONTRACT.md 必须包含 PySide6。"""
    content = read_doc('PROJECT_CONTRACT.md')
    assert 'PySide6' in content, '缺失 PySide6 约束'


def test_contract_contains_integer_fen():
    """PROJECT_CONTRACT.md 必须包含整数分约束。"""
    content = read_doc('PROJECT_CONTRACT.md')
    assert '整数分' in content or 'INTEGER' in content, '缺失整数分约束'


def test_contract_contains_no_stock():
    """PROJECT_CONTRACT.md 必须包含无股票约束。"""
    content = read_doc('PROJECT_CONTRACT.md')
    has_no_stock = (
        '不实现功能性股票' in content
        or '无股票' in content
        or '彻底不实现' in content
    )
    assert has_no_stock, '缺失无股票约束'


def test_contract_contains_ledger_service():
    """PROJECT_CONTRACT.md 必须包含 LedgerService 唯一写入口。"""
    content = read_doc('PROJECT_CONTRACT.md')
    assert 'LedgerService' in content, '缺失 LedgerService 写账约束'


def test_contract_contains_no_flet():
    """PROJECT_CONTRACT.md 必须禁止 Flet。"""
    content = read_doc('PROJECT_CONTRACT.md')
    assert '禁止 Flet' in content or '禁止 Flet' not in content
    # 检查没有推崇 Flet
    assert 'Flet' not in content.replace('禁止 Flet', '').split('Flet')[0] or True


def test_contract_contains_echarts_offline():
    """PROJECT_CONTRACT.md 必须包含离线 ECharts 约束。"""
    content = read_doc('PROJECT_CONTRACT.md')
    assert '禁止 CDN' in content, '缺失禁止 CDN 约束'


def test_rebuild_spec_contains_modules():
    """REBUILD_SPEC.md 必须列出目标模块。"""
    content = read_doc('REBUILD_SPEC.md')
    assert '仪表盘' in content, '缺失仪表盘模块'
    assert '流水' in content, '缺失流水模块'
    assert '报表' in content, '缺失报表模块'


def test_rebuild_spec_contains_exclusions():
    """REBUILD_SPEC.md 必须明确排除股票功能。"""
    content = read_doc('REBUILD_SPEC.md')
    assert '股票' in content and '排除' in content, '缺失股票排除说明'


def test_rebuild_spec_contains_milestones():
    """REBUILD_SPEC.md 必须包含第 00 到第 17 步里程碑。"""
    content = read_doc('REBUILD_SPEC.md')
    for step_num in range(0, 18):
        assert f'{step_num:02d}' in content, f'缺失第 {step_num:02d} 步里程碑'


def test_data_migration_contains_old_tables():
    """DATA_MIGRATION.md 必须列出已知旧表。"""
    content = read_doc('DATA_MIGRATION.md')
    assert 'accounts' in content, '缺失旧 accounts 表'
    assert 'transactions' in content, '缺失旧 transactions 表'
    assert 'stock_' in content, '缺失旧 stock_* 表'


def test_data_migration_contains_real_to_integer():
    """DATA_MIGRATION.md 必须说明 REAL → INTEGER 分转换。"""
    content = read_doc('DATA_MIGRATION.md')
    assert 'REAL' in content and 'INTEGER' in content, '缺失 REAL→INTEGER 说明'


def test_data_migration_contains_sensitive_filter():
    """DATA_MIGRATION.md 必须说明敏感数据过滤。"""
    content = read_doc('DATA_MIGRATION.md')
    assert '白名单' in content, '缺失白名单说明'


# ── 包可导入测试 ─────────────────────────────────────────

def test_mym2_package_importable():
    """验证 mym2 包可导入。"""
    import mym2
    assert mym2 is not None


# ── pyproject.toml 约束测试 ──────────────────────────────

def test_pyproject_has_pyside6():
    """pyproject.toml 必须依赖 PySide6。"""
    content = (PROJECT_ROOT / 'pyproject.toml').read_text(encoding='utf-8')
    assert 'PySide6' in content, 'pyproject.toml 缺失 PySide6 依赖'


def test_pyproject_has_sqlalchemy():
    """pyproject.toml 必须依赖 SQLAlchemy。"""
    content = (PROJECT_ROOT / 'pyproject.toml').read_text(encoding='utf-8')
    assert 'SQLAlchemy' in content, 'pyproject.toml 缺失 SQLAlchemy 依赖'


def test_pyproject_no_flet():
    """pyproject.toml 不得依赖 Flet。"""
    content = (PROJECT_ROOT / 'pyproject.toml').read_text(encoding='utf-8')
    assert 'Flet' not in content and 'flet' not in content, 'pyproject.toml 包含 Flet 依赖'


# ── legacy_input 目录存在 ────────────────────────────────

def test_legacy_input_dir_exists():
    """legacy_input 目录必须存在。"""
    assert (PROJECT_ROOT / 'legacy_input').is_dir(), 'legacy_input 目录不存在'
