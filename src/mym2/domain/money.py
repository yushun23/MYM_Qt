"""Money 值对象 — 不可变金额容器。

所有金额以 INTEGER 分存储和运算，禁止 float/REAL。
仅通过 `from_decimal_text` 将用户输入的十进制文本转为分。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

# 合法十进制金额字符串：可选负号 + 整数部分 + 可选小数部分（最多2位）
_DECIMAL_TEXT_RE = re.compile(r'^-?\d+(\.\d{1,2})?$')

# 最大金额：9 万亿分（约 900 亿元），防止溢出
_MAX_MINOR = 900_000_000_000_00  # 9e13 分


@dataclass(frozen=True, slots=True)
class Money:
    """不可变金额值对象。

    Attributes:
        minor: 以整数分表示的金额。正数/负数方向由交易类型决定。
    """

    minor: int

    def __post_init__(self) -> None:
        if not isinstance(self.minor, int):
            raise TypeError(f'minor 必须为 int，实际为 {type(self.minor).__name__}')
        if abs(self.minor) > _MAX_MINOR:
            raise ValueError(f'金额绝对值过大: {self.minor}')

    @classmethod
    def from_decimal_text(cls, text: str) -> Money:
        """从十进制金额文本创建 Money。

        输入如 "12.34" → 1234 分，"100" → 10000 分。
        严格拒绝：NaN、科学计数法、超过两位小数、空值。

        Args:
            text: 十进制金额字符串，如 "12.34"。

        Returns:
            Money 实例。

        Raises:
            ValueError: 格式不合法。
        """
        if not isinstance(text, str):
            raise ValueError(f'金额文本必须为 str，实际为 {type(text).__name__}')
        text = text.strip()
        if not text or text in ('nan', 'NaN', 'NAN', 'inf', '-inf', 'Infinity', '-Infinity'):
            raise ValueError(f'无效金额文本: {text!r}')

        if not _DECIMAL_TEXT_RE.match(text):
            if 'e' in text.lower():
                raise ValueError(f'拒绝科学计数法: {text!r}')
            raise ValueError(f'金额格式不合法（需为最多两位小数的十进制数）: {text!r}')

        try:
            d = Decimal(text)
        except InvalidOperation:
            raise ValueError(f'无法解析金额: {text!r}') from None

        # 转为分：乘以 100 并取整。使用 quantize 确保精确转换。
        minor = int((d * 100).quantize(Decimal('1')))
        return cls(minor=minor)

    def format(
        self,
        *,
        show_sign: bool = False,
        thousands_sep: bool = True,
    ) -> str:
        """将金额格式化为用户可读的元显示。

        Args:
            show_sign: 是否在正数前显示 + 号。
            thousands_sep: 是否添加千分位逗号。

        Returns:
            格式化的字符串，如 "1,234.56" 或 "-99.00"。
        """
        yuan = Decimal(self.minor) / 100

        if thousands_sep:
            # 手动构建千分位格式（避免 locale 依赖）
            sign = ''
            val = yuan
            if val < 0:
                sign = '-'
                val = -val
            elif show_sign and val > 0:
                sign = '+'

            int_part, _, frac_part = str(abs(val)).partition('.')
            frac_part = (frac_part + '00')[:2]

            if int_part == '0':
                formatted_int = '0'
            else:
                # 每三位加逗号
                chunks = []
                while len(int_part) > 3:
                    chunks.append(int_part[-3:])
                    int_part = int_part[:-3]
                chunks.append(int_part)
                formatted_int = ','.join(reversed(chunks))

            return f'{sign}{formatted_int}.{frac_part}'
        else:
            val = Decimal(self.minor) / 100
            formatted = f'{val:.2f}'
            if show_sign and self.minor > 0:
                formatted = f'+{formatted}'
            return formatted

    def __neg__(self) -> Money:
        return Money(minor=-self.minor)

    def __abs__(self) -> Money:
        return Money(minor=abs(self.minor))

    def __add__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        return Money(minor=self.minor + other.minor)

    def __sub__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        return Money(minor=self.minor - other.minor)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.minor == other.minor

    def __hash__(self) -> int:
        return hash(self.minor)

    def __repr__(self) -> str:
        return f'Money(minor={self.minor})'


def validate_positive_amount_minor(value: int) -> int:
    """验证金额为正整数分（不含交易方向）。

    交易方向由交易类型决定，此处只要求金额 > 0。

    Args:
        value: 金额（分）。

    Returns:
        验证通过的原值。

    Raises:
        ValueError: 金额 ≤ 0 或非整数。
    """
    if not isinstance(value, int):
        raise ValueError(f'金额必须为整数，实际为 {type(value).__name__}')
    if value <= 0:
        raise ValueError(f'金额必须为正整数，实际为 {value}')
    if value > _MAX_MINOR:
        raise ValueError(f'金额绝对值过大: {value}')
    return value
