import ast
import json
import math
import operator

BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

SAFE_FUNCTIONS = {
    "round": round,
    "abs": abs,
    "sqrt": math.sqrt,
    "ceil": math.ceil,
    "floor": math.floor,
}

MAX_EXPONENT = 1000


class UnsafeExpressionError(Exception):
    """Raised when an expression contains non-whitelisted AST nodes."""


class SafeMathEvaluator(ast.NodeVisitor):
    def visit_Expression(self, node: ast.Expression):
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise UnsafeExpressionError(f"Unsupported constant type: {type(node.value).__name__}")

    def visit_BinOp(self, node: ast.BinOp):
        op_func = BINARY_OPS.get(type(node.op))
        if not op_func:
            raise UnsafeExpressionError(f"Unsupported binary operator: {type(node.op).__name__}")
        left = self.visit(node.left)
        right = self.visit(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise UnsafeExpressionError(f"Exponent {right} exceeds safety limit ({MAX_EXPONENT}).")
        return op_func(left, right)

    def visit_UnaryOp(self, node: ast.UnaryOp):
        op_func = UNARY_OPS.get(type(node.op))
        if not op_func:
            raise UnsafeExpressionError(f"Unsupported unary operator: {type(node.op).__name__}")
        return op_func(self.visit(node.operand))

    def visit_Call(self, node: ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in SAFE_FUNCTIONS:
            raise UnsafeExpressionError("Function calls are restricted to whitelisted math functions.")
        if node.keywords:
            raise UnsafeExpressionError("Keyword arguments are not permitted.")
        args = [self.visit(arg) for arg in node.args]
        return SAFE_FUNCTIONS[node.func.id](*args)

    def generic_visit(self, node: ast.AST):
        raise UnsafeExpressionError(
            f"Security Policy Violation: Disallowed syntax construct '{type(node).__name__}'."
        )


def evaluate_safe_math(expression: str) -> str:
    """Safely parses and evaluates an arithmetic expression via Python AST."""
    if not expression or len(expression) > 256:
        return json.dumps({"status": "ERROR", "error": "Expression must be 1-256 characters."})

    normalized = expression.strip()
    try:
        tree = ast.parse(normalized, mode="eval")
        result = SafeMathEvaluator().visit(tree)
        return json.dumps(
            {
                "status": "OK",
                "expression": normalized,
                "result": round(result, 6) if isinstance(result, float) else result,
            }
        )
    except UnsafeExpressionError as sec_err:
        return json.dumps({"status": "BLOCKED", "error": str(sec_err)})
    except ZeroDivisionError:
        return json.dumps({"status": "MATH_ERROR", "error": "Division by zero."})
    except SyntaxError:
        return json.dumps({"status": "SYNTAX_ERROR", "error": "Invalid arithmetic syntax."})
