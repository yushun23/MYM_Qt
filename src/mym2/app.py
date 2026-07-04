"""MYM2 应用程序入口。

用法:
    python -m mym2.app           # 使用默认数据目录
    python -m mym2.app --dev     # 使用项目目录下 data/（开发用）
"""

import argparse
import sys
from pathlib import Path

from mym2.bootstrap import bootstrap


def main() -> None:
    """MYM2 主入口。"""
    parser = argparse.ArgumentParser(description='MYM2 个人记账软件')
    parser.add_argument(
        '--dev',
        action='store_true',
        help='开发模式：数据目录使用项目根下的 data/',
    )
    args = parser.parse_args()

    data_dir = None
    if args.dev:
        project_root = Path(__file__).resolve().parent.parent.parent
        data_dir = project_root / 'data'

    window = bootstrap(data_dir=data_dir)
    window.show()

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is not None:
        sys.exit(app.exec())


if __name__ == '__main__':
    main()
