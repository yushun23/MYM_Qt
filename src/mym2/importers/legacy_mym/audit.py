"""旧 .mym 迁移前审计 — 主入口。

用法：
    python -m mym2.importers.legacy_mym.audit <file.mym> --out <目录>

仅执行只读检查，不写入目标业务数据。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from mym2.importers.legacy_mym.reporting import ReportGenerator
from mym2.importers.legacy_mym.schema_probe import SchemaProbe
from mym2.importers.legacy_mym.source_reader import SourceReader

logger = logging.getLogger('mym2.importers.legacy_mym.audit')


def audit_mym_file(
    file_path: str | Path,
    output_dir: str | Path,
) -> dict:
    """对旧 .mym 文件执行完整只读审计。

    Args:
        file_path: 旧 .mym 文件路径。
        output_dir: 报告输出目录。

    Returns:
        审计结果字典（与 JSON 报告同结构）。

    Raises:
        FileNotFoundError: 文件或旧源码目录缺失。
        ValueError: 文件无效或损坏。
    """
    file_path = Path(file_path).resolve()
    output_dir = Path(output_dir).resolve()

    # 检查 legacy_input 约定路径
    _check_legacy_input_presence(file_path)

    logger.info('开始审计: %s', file_path)

    # 1. 只读打开 & 探测
    with SourceReader(file_path) as reader:
        probe = SchemaProbe(reader)
        result = probe.probe()

        source_hash = reader.file_hash_before or ''
        hash_unchanged = reader.is_hash_unchanged

    # 2. 生成报告
    gen = ReportGenerator(
        result=result,
        source_path=str(file_path),
        source_hash=source_hash,
        hash_unchanged=hash_unchanged,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = file_path.stem

    json_path = output_dir / f'{stem}_audit.json'
    md_path = output_dir / f'{stem}_audit.md'

    gen.write_json(json_path)
    gen.write_markdown(md_path)

    logger.info('JSON 报告: %s', json_path)
    logger.info('Markdown 报告: %s', md_path)

    # 打印摘要
    _print_summary(result, file_path, source_hash, hash_unchanged)

    return gen._build_data()  # noqa: SLF001


def _check_legacy_input_presence(mym_path: Path) -> None:
    """检查 legacy_input 约定路径下的文件是否存在。

    若 my_money.mym 或 MYM-main/ 缺失，生成明确缺失报告。
    """
    legacy_dir = mym_path.parent if mym_path.parent.name == 'legacy_input' else None
    warnings: list[str] = []

    if not mym_path.exists():
        raise FileNotFoundError(
            f'旧账套文件不存在: {mym_path}\n'
            f'请将旧 .mym 文件放置到 {mym_path}'
        )

    # 检查 MYM-main 源码目录
    if legacy_dir:
        source_dir = legacy_dir / 'MYM-main'
        if not source_dir.exists():
            warnings.append(
                f'旧源码目录不存在: {source_dir}\n'
                f'迁移仍可进行，但缺少源码参考可能影响某些字段的解析。'
            )
    else:
        # 不在 legacy_input 下，但文件存在，给出提示
        logger.info('注意: .mym 文件不在 legacy_input/ 约定路径下')

    if warnings:
        for w in warnings:
            logger.warning(w)


def _print_summary(result, file_path, source_hash, hash_unchanged) -> None:
    """在控制台打印审计摘要。"""
    r = result
    print(file=sys.stderr)
    print('=' * 60, file=sys.stderr)
    print('  MYM2 旧账套迁移前审计 — 摘要', file=sys.stderr)
    print('=' * 60, file=sys.stderr)
    print(f'  文件: {file_path}', file=sys.stderr)
    print(f'  SHA-256: {source_hash[:16]}...', file=sys.stderr)
    print(f'  文件未修改: {"✅ 是" if hash_unchanged else "❌ 否"}', file=sys.stderr)
    print(f'  完整性: {"✅ 通过" if not r.integrity_errors else "❌ 失败"}', file=sys.stderr)
    fk_status = (
        "✅ 通过" if not r.foreign_key_violations
        else f"⚠️ {len(r.foreign_key_violations)} 行"
    )
    print(f'  外表约束: {fk_status}', file=sys.stderr)
    print(f'  表数量: {len(r.tables)}', file=sys.stderr)
    print(f'  总行数: {sum(t.row_count for t in r.tables.values())}', file=sys.stderr)
    print(f'  REAL 金额异常: {len(r.real_anomalies)}', file=sys.stderr)
    print(f'  交易类型: {len(r.transaction_type_counts)}', file=sys.stderr)
    print(f'  链接证券账户: {len(r.linked_stock_accounts)}', file=sys.stderr)
    print(f'  余额差异账户: {len(r.balance_diffs)}', file=sys.stderr)
    print(f'  Settings 键: {r.settings_key_count}', file=sys.stderr)
    print(f'    敏感键: {len(r.settings_sensitive_keys)}（值已跳过）', file=sys.stderr)
    if r.warnings:
        print(f'  警告: {len(r.warnings)}', file=sys.stderr)
    print('=' * 60, file=sys.stderr)


def main() -> None:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        description='MYM2 旧 .mym 迁移前审计',
    )
    parser.add_argument(
        'file',
        help='旧 .mym 文件路径（如 legacy_input/my_money.mym）',
    )
    parser.add_argument(
        '--out', '-o',
        default='reports',
        help='报告输出目录（默认: reports）',
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='详细日志输出',
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(levelname)s [%(name)s] %(message)s',
        stream=sys.stderr,
    )

    try:
        audit_mym_file(args.file, args.out)
    except FileNotFoundError as e:
        print(f'错误: {e}', file=sys.stderr)
        sys.exit(2)
    except ValueError as e:
        print(f'错误: {e}', file=sys.stderr)
        sys.exit(3)
    except Exception as e:
        logger.exception('审计失败')
        print(f'错误: {e}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
