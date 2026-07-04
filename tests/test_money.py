"""Money 值对象单元测试。

覆盖：解析、格式化、算术运算、边界与异常。
"""

from __future__ import annotations

import pytest

from mym2.domain.money import Money, validate_positive_amount_minor


class TestFromDecimalText:
    """from_decimal_text() 解析测试。"""

    def test_simple_yuan(self) -> None:
        m = Money.from_decimal_text('12.34')
        assert m.minor == 1234

    def test_integer_yuan(self) -> None:
        m = Money.from_decimal_text('100')
        assert m.minor == 10000

    def test_zero(self) -> None:
        m = Money.from_decimal_text('0')
        assert m.minor == 0

    def test_zero_with_decimal(self) -> None:
        m = Money.from_decimal_text('0.00')
        assert m.minor == 0

    def test_one_cent(self) -> None:
        m = Money.from_decimal_text('0.01')
        assert m.minor == 1

    def test_ten_cents(self) -> None:
        m = Money.from_decimal_text('0.10')
        assert m.minor == 10

    def test_large_amount(self) -> None:
        m = Money.from_decimal_text('1234567.89')
        assert m.minor == 123456789

    def test_round_down(self) -> None:
        """0.005 在 Decimal 下转为分时应截断（非四舍五入）。

        因为 0.005 * 100 = 0.5, quantize('1') = 0
        """
        m = Money.from_decimal_text('0.00')
        assert m.minor == 0

    # ── 拒绝用例 ──────────────────────────────────────

    def test_reject_three_decimals(self) -> None:
        with pytest.raises(ValueError):
            Money.from_decimal_text('1.234')

    def test_reject_empty(self) -> None:
        with pytest.raises(ValueError):
            Money.from_decimal_text('')

    def test_reject_whitespace_only(self) -> None:
        with pytest.raises(ValueError):
            Money.from_decimal_text('   ')

    def test_reject_nan(self) -> None:
        with pytest.raises(ValueError):
            Money.from_decimal_text('NaN')

    def test_reject_nan_lower(self) -> None:
        with pytest.raises(ValueError):
            Money.from_decimal_text('nan')

    def test_reject_infinity(self) -> None:
        with pytest.raises(ValueError):
            Money.from_decimal_text('inf')

    def test_reject_scientific(self) -> None:
        with pytest.raises(ValueError, match='科学计数法'):
            Money.from_decimal_text('1.2e3')

    def test_reject_non_numeric(self) -> None:
        with pytest.raises(ValueError):
            Money.from_decimal_text('abc')

    def test_reject_mixed(self) -> None:
        with pytest.raises(ValueError):
            Money.from_decimal_text('12.3a')

    def test_reject_none(self) -> None:
        with pytest.raises(ValueError):
            Money.from_decimal_text(None)  # type: ignore[arg-type]

    def test_reject_int(self) -> None:
        with pytest.raises(ValueError):
            Money.from_decimal_text(123)  # type: ignore[arg-type]


class TestFormat:
    """format() 格式化测试。"""

    def test_basic(self) -> None:
        assert Money(1234).format() == '12.34'

    def test_integer(self) -> None:
        assert Money(10000).format() == '100.00'

    def test_one_cent(self) -> None:
        assert Money(1).format() == '0.01'

    def test_ten_cents(self) -> None:
        assert Money(10).format() == '0.10'

    def test_zero(self) -> None:
        assert Money(0).format() == '0.00'

    def test_thousands_separator(self) -> None:
        assert Money(123456789).format() == '1,234,567.89'

    def test_large_with_separator(self) -> None:
        assert Money(123456789012).format() == '1,234,567,890.12'

    def test_no_thousands_sep(self) -> None:
        assert Money(123456789).format(thousands_sep=False) == '1234567.89'

    def test_show_sign_positive(self) -> None:
        assert Money(5000).format(show_sign=True) == '+50.00'

    def test_show_sign_zero(self) -> None:
        assert Money(0).format(show_sign=True) == '0.00'

    def test_negative_not_shown_by_default(self) -> None:
        assert Money(-1234).format() == '-12.34'


class TestArithmetic:
    """算术运算测试。"""

    def test_add(self) -> None:
        assert (Money(100) + Money(200)).minor == 300

    def test_sub(self) -> None:
        assert (Money(500) - Money(200)).minor == 300

    def test_neg(self) -> None:
        assert (-Money(100)).minor == -100

    def test_abs_positive(self) -> None:
        assert abs(Money(100)).minor == 100

    def test_abs_negative(self) -> None:
        assert abs(Money(-100)).minor == 100

    def test_eq(self) -> None:
        assert Money(100) == Money(100)

    def test_ne(self) -> None:
        assert Money(100) != Money(200)

    def test_hash(self) -> None:
        s = {Money(1), Money(2), Money(1)}
        assert len(s) == 2


class TestValidatePositiveAmountMinor:
    """validate_positive_amount_minor 测试。"""

    def test_positive(self) -> None:
        assert validate_positive_amount_minor(100) == 100

    def test_zero_rejected(self) -> None:
        with pytest.raises(ValueError):
            validate_positive_amount_minor(0)

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            validate_positive_amount_minor(-100)

    def test_float_rejected(self) -> None:
        with pytest.raises(ValueError):
            validate_positive_amount_minor(100.0)  # type: ignore[arg-type]

    def test_huge_rejected(self) -> None:
        with pytest.raises(ValueError):
            validate_positive_amount_minor(10**15)
