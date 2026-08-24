"""表达式组合的纯函数，观察区与 MemoryEngine 共用。"""

OPERATOR_PREFIXES = ("+", "-", "*", "/", "%", "<<", ">>", "&", "|", "^")


def starts_with_operator(expression: str) -> bool:
    """判断表达式是否以运算符开头，用于决定子项是否继承父级表达式。"""
    return bool(expression and expression.lstrip().startswith(OPERATOR_PREFIXES))


def compose_expression(parent_expr: str, child_expr: str) -> str:
    """
    组合父子表达式。

    子项以运算符开头时继承父级有效表达式，否则作为独立表达式使用。
    """
    child = (child_expr or "").strip()
    if not parent_expr:
        return child
    if starts_with_operator(child):
        return f"({parent_expr}) {child}"
    return child