import pytest

from finagent.mcp_server.tools import CalcError, calculate_expr


@pytest.mark.parametrize(
    "expr,want",
    [("19.1 - 17.8", 1.3), ("(763.8 - 1022.3) / 1022.3 * 100", -25.287), ("-3 + 2*4", 5.0),
     ("1e3 / 4", 250.0), ("((2))", 2.0)],
)  # fmt: skip
def test_arithmetic(expr, want):
    assert calculate_expr(expr) == pytest.approx(want, abs=1e-3)


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('ls')",
        "open('/etc/passwd').read()",
        "().__class__.__bases__[0].__subclasses__()",
        "x + 1",
        "[1, 2]",
        "'a' * 3",
        "2 ** 1000000",
        "9 ** 9 ** 9",
        "lambda: 1",
        "1 if True else 2",
        "abs(-1)",
        "1; 2",
        "",
        "1 / 0",
        "1" * 300,
    ],
)
def test_hostile_or_invalid_input_is_rejected(expr):
    with pytest.raises(CalcError):
        calculate_expr(expr)
