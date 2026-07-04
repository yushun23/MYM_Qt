"""MYM2 数据库模型集合。

导入顺序确保关系解析正确：
account → category → transaction → budget → 其余辅助模型。
"""

from mym2.db.models.account import Account
from mym2.db.models.app_setting import AppSetting
from mym2.db.models.audit_event import AuditEvent
from mym2.db.models.budget import BudgetLine, BudgetPeriod
from mym2.db.models.category import Category
from mym2.db.models.import_run import ImportRun
from mym2.db.models.legacy import LegacyArchiveRecord, LegacyIdMap
from mym2.db.models.transaction import Transaction

__all__ = [
    'Account',
    'AppSetting',
    'AuditEvent',
    'BudgetLine',
    'BudgetPeriod',
    'Category',
    'ImportRun',
    'LegacyArchiveRecord',
    'LegacyIdMap',
    'Transaction',
]
