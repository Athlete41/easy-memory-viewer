import unittest

from common.expression import compose_expression, starts_with_operator


class ExpressionComposeTests(unittest.TestCase):
    def test_child_with_operator_inherits(self):
        parent = "[xxx.exe + 0x123] + 0x111"
        child = "+ 0x4"
        self.assertEqual(
            compose_expression(parent, child),
            "([xxx.exe + 0x123] + 0x111) + 0x4",
        )

    def test_child_without_operator_is_independent(self):
        parent = "[xxx.exe + 0x123] + 0x111"
        child = "[yyy.exe + 0x1]"
        self.assertEqual(compose_expression(parent, child), child)

    def test_multi_level_inheritance(self):
        root = "0x1000"
        child = compose_expression(root, "+ 0x4")
        grandchild = compose_expression(child, "* 2")
        self.assertEqual(grandchild, "((0x1000) + 0x4) * 2")

    def test_starts_with_operator(self):
        self.assertTrue(starts_with_operator("+ 4"))
        self.assertTrue(starts_with_operator("-0x10"))
        self.assertFalse(starts_with_operator("[xxx.exe + 1]"))

    def test_empty_parent_returns_child(self):
        self.assertEqual(compose_expression("", "+ 0x4"), "+ 0x4")


if __name__ == "__main__":
    unittest.main()