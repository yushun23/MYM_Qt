"""审计报告生成器。

从 ProbeResult 生成 JSON 和可读 Markdown 报告。
settings 具体值一律不展示。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mym2.importers.legacy_mym.schema_probe import ProbeResult

_REPORT_VERSION = '1.0.0'

# 敏感 settings 键模式
_SENSITIVE_KEY_PATTERNS: tuple[str, ...] = (
    'password', 'secret', 'token', 'key', 'api', 'hash',
    'proxy_username', 'proxy_url', 'auth',
)


class ReportGenerator:
    """审计报告生成器。"""

    def __init__(self, result: ProbeResult, source_path: str,
                 source_hash: str, hash_unchanged: bool):
        self._result = result
        self._source_path = source_path
        self._source_hash = source_hash
        self._hash_unchanged = hash_unchanged
        self._generated_at = datetime.now(UTC).replace(tzinfo=None).isoformat()

    # ── JSON ──────────────────────────────────────────

    def to_json(self) -> str:
        """生成 JSON 格式审计报告。"""
        data = self._build_data()
        return json.dumps(data, ensure_ascii=False, indent=2, default=str)

    def write_json(self, output_path: Path) -> None:
        """写入 JSON 报告到文件。"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(self.to_json())

    # ── Markdown ──────────────────────────────────────

    def to_markdown(self) -> str:
        """生成 Markdown 格式审计报告。"""
        lines: list[str] = []
        d = self._build_data()
        meta = d['meta']
        summary = d['summary']
        integrity = d['integrity']

        # 标题
        lines.append('# MYM2 旧账套迁移前审计报告')
        lines.append('')
        lines.append(f'> 生成时间: {self._generated_at}')
        lines.append(f'> 报告版本: {_REPORT_VERSION}')
        lines.append('')

        # 文件信息
        lines.append('## 1. 文件信息')
        lines.append('')
        lines.append(f'- **源文件**: `{meta["source_path"]}`')
        lines.append(f'- **SHA-256**: `{meta["source_hash"]}`')
        hash_ok = meta['hash_unchanged']
        lines.append(f'- **文件未修改**: {"✅ 是" if hash_ok else "❌ 否"}')
        lines.append('')

        # 完整性
        lines.append('## 2. 完整性检查')
        lines.append('')
        if integrity['integrity_ok']:
            lines.append('- ✅ **integrity_check**: 通过')
        else:
            lines.append('- ❌ **integrity_check**: 失败')
            for err in integrity['integrity_errors']:
                lines.append(f'  - {err}')
        if integrity['fk_ok']:
            lines.append('- ✅ **foreign_key_check**: 通过（0 行违规）')
        else:
            lines.append(f'- ⚠️ **foreign_key_check**: {integrity["fk_violations"]} 行违规')
        lines.append('')

        # 表概览
        lines.append('## 3. 表概览')
        lines.append('')
        lines.append('| 表名 | 行数 | REAL 列 |')
        lines.append('|------|------|---------|')
        for tbl in summary['tables']:
            real_cols = ', '.join(tbl['real_columns']) if tbl['real_columns'] else '—'
            lines.append(f'| `{tbl["name"]}` | {tbl["row_count"]} | {real_cols} |')
        lines.append('')

        # 核心表缺失
        if summary.get('missing_core_tables'):
            lines.append('### ⚠️ 缺失核心表')
            lines.append('')
            for t in summary['missing_core_tables']:
                lines.append(f'- {t}')
            lines.append('')

        # REAL 金额异常
        if summary['real_anomalies']:
            lines.append('## 4. REAL 金额类型风险')
            lines.append('')
            lines.append('以下列存储为 REAL 类型，转换为 INTEGER 分时存在精度风险：')
            lines.append('')
            for a in summary['real_anomalies']:
                lines.append(f'- **`{a["table"]}.{a["column"]}`**: {a["description"]}')
            lines.append('')

        # 交易类型统计
        if summary['transaction_types']:
            lines.append('## 5. 交易类型分布')
            lines.append('')
            lines.append('| 类型 | 笔数 |')
            lines.append('|------|------|')
            for tt, cnt in summary['transaction_types'].items():
                lines.append(f'| `{tt}` | {cnt} |')
            lines.append('')

        # 链接证券账户
        if summary['linked_stock_accounts']:
            lines.append('## 6. 链接证券账户')
            lines.append('')
            lines.append('以下账户与股票/证券模块关联，余额不可由普通流水重算：')
            lines.append('')
            lines.append('| ID | 名称 | 余额 (元) | 关联股票账户 | 系统锁定 |')
            lines.append('|----|------|----------|-------------|---------|')
            for a in summary['linked_stock_accounts']:
                linked = a['linked_stock_account_id'] or '—'
                locked = '是' if a['is_system_locked'] else '否'
                lines.append(
                    f'| {a["account_id"]} | {a["account_name"]} | '
                    f'{a["balance_real"]:.2f} | {linked} | {locked} |'
                )
            lines.append('')

        # 股票相关表
        if summary.get('stock_tables'):
            lines.append('### 股票相关表（将归档）')
            lines.append('')
            for t in summary['stock_tables']:
                lines.append(f'- `{t}`')
            lines.append('')

        # 余额差异
        if summary['balance_diffs']:
            lines.append('## 7. 账户余额差异（流水重算 vs 存储余额）')
            lines.append('')
            lines.append('> 仅统计非链接证券账户。链接证券账户由股票估值系统管理，不在此列。')
            lines.append('')
            lines.append('| 账户 | 存储余额 | 重算余额 | 差异 (元) | 差异 (分) | 说明 |')
            lines.append('|------|---------|---------|----------|----------|------|')
            for d in summary['balance_diffs']:
                lines.append(
                    f'| {d["account_name"]} | {d["stored_balance_real"]:.2f} | '
                    f'{d["computed_balance_real"]:.2f} | {d["diff_real"]:+.2f} | '
                    f'{d["diff_minor"]:+d} | {d["note"]} |'
                )
            lines.append('')

        # Settings
        lines.append('## 8. Settings 检测')
        lines.append('')
        lines.append(f'- 总键数: {summary["settings_key_count"]}')
        if summary['settings_sensitive_keys']:
            sensitive_count = len(summary['settings_sensitive_keys'])
            lines.append(f'- 敏感键数: {sensitive_count}')
            lines.append('  （值已跳过，不展示）')
            lines.append('')
            lines.append('**敏感键列表（仅键名，值已跳过）：**')
            lines.append('')
            for k in summary['settings_sensitive_keys']:
                lines.append(f'- `{k}`')
        else:
            lines.append('- 未检测到敏感键')
        lines.append('')

        # 警告
        if summary.get('warnings'):
            lines.append('## 9. 警告')
            lines.append('')
            for w in summary['warnings']:
                lines.append(f'- ⚠️ {w}')
            lines.append('')

        # 页脚
        lines.append('---')
        lines.append('')
        lines.append(f'*报告由 MYM2 迁移审计工具生成 · {self._generated_at}*')
        lines.append('')

        return '\n'.join(lines)

    def write_markdown(self, output_path: Path) -> None:
        """写入 Markdown 报告到文件。"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(self.to_markdown())

    # ── 内部 ──────────────────────────────────────────

    def _build_data(self) -> dict[str, Any]:
        """构建报告数据结构。"""
        r = self._result

        missing_core = [t for t in ('accounts', 'transactions', 'categories')
                        if t not in r.tables]

        stock_tables = [t for t in r.tables
                        if t.startswith('stock_') and r.tables[t].row_count > 0]

        return {
            'meta': {
                'report_version': _REPORT_VERSION,
                'generated_at': self._generated_at,
                'source_path': self._source_path,
                'source_hash': self._source_hash,
                'hash_unchanged': self._hash_unchanged,
            },
            'integrity': {
                'integrity_ok': len(r.integrity_errors) == 0,
                'integrity_errors': r.integrity_errors,
                'fk_ok': len(r.foreign_key_violations) == 0,
                'fk_violations': len(r.foreign_key_violations),
            },
            'summary': {
                'table_count': len(r.tables),
                'total_rows': sum(t.row_count for t in r.tables.values()),
                'tables': [
                    {
                        'name': t.name,
                        'row_count': t.row_count,
                        'column_count': len(t.columns),
                        'real_columns': t.real_columns,
                    }
                    for t in r.tables.values()
                ],
                'missing_core_tables': missing_core,
                'real_anomalies': [
                    {
                        'table': a.table,
                        'column': a.column,
                        'description': a.description,
                    }
                    for a in r.real_anomalies
                ],
                'transaction_types': r.transaction_type_counts,
                'linked_stock_accounts': [
                    {
                        'account_id': a.account_id,
                        'account_name': a.account_name,
                        'balance_real': a.balance_real,
                        'linked_stock_account_id': a.linked_stock_account_id,
                        'is_system_locked': a.is_system_locked,
                    }
                    for a in r.linked_stock_accounts
                ],
                'stock_tables': stock_tables,
                'balance_diffs': [
                    {
                        'account_id': d.account_id,
                        'account_name': d.account_name,
                        'stored_balance_real': d.stored_balance_real,
                        'computed_balance_real': d.computed_balance_real,
                        'diff_real': d.diff_real,
                        'diff_minor': d.diff_minor,
                        'note': d.note,
                    }
                    for d in r.balance_diffs
                ],
                'settings_key_count': r.settings_key_count,
                'settings_sensitive_keys': r.settings_sensitive_keys,
                'warnings': r.warnings,
            },
        }
