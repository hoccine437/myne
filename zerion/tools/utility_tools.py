# tools/utility_tools.py
"""
Small, safe, stateless utility tools. All stdlib, no network, no
filesystem access — nothing here can do damage, so none are destructive.
"""

import ast
import base64 as b64
import hashlib
import json
import operator
import random
import uuid as uuid_lib

from tools.base import Tool, ToolResult

# Safe arithmetic-only evaluator — no eval(), no arbitrary code execution.
_ALLOWED_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _safe_eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("expression contains disallowed syntax")


class CalculatorTool(Tool):
    name = "calculate"
    description = "Evaluate a math expression (e.g. '12 * (3 + 4)')."
    parameters = {"expression": "a math expression string"}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        expr = str(parameters.get("expression", "")).strip()
        if not expr:
            return ToolResult.fail(error="missing_parameter", message="No expression provided.")
        try:
            tree = ast.parse(expr, mode="eval")
            result = _safe_eval(tree.body)
            return ToolResult.ok(data=result, message=f"{expr} = {result}")
        except Exception as e:
            return ToolResult.fail(error="invalid_expression", message=f"Couldn't evaluate that: {e}")


class RandomTool(Tool):
    name = "random_number"
    description = "Generate a random integer between min and max (inclusive)."
    parameters = {"min": "lower bound (default 0)", "max": "upper bound (default 100)"}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        try:
            lo = int(parameters.get("min", 0))
            hi = int(parameters.get("max", 100))
            if lo > hi:
                lo, hi = hi, lo
            value = random.randint(lo, hi)
            return ToolResult.ok(data=value, message=f"Random number: {value}")
        except Exception as e:
            return ToolResult.fail(error="invalid_parameters", message=str(e))


class UUIDTool(Tool):
    name = "generate_uuid"
    description = "Generate a random UUID (v4)."
    parameters = {}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        value = str(uuid_lib.uuid4())
        return ToolResult.ok(data=value, message=value)


class HashTool(Tool):
    name = "hash_text"
    description = "Compute a hash (md5, sha1, or sha256) of a text string."
    parameters = {"text": "text to hash", "algorithm": "md5, sha1, or sha256 (default sha256)"}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        text = str(parameters.get("text", ""))
        algo = str(parameters.get("algorithm", "sha256")).lower()
        if not text:
            return ToolResult.fail(error="missing_parameter", message="No text provided.")
        if algo not in ("md5", "sha1", "sha256"):
            return ToolResult.fail(error="invalid_parameter", message="algorithm must be md5, sha1, or sha256.")
        digest = hashlib.new(algo, text.encode("utf-8")).hexdigest()
        return ToolResult.ok(data=digest, message=digest)


class Base64Tool(Tool):
    name = "base64_convert"
    description = "Encode or decode text using base64."
    parameters = {"text": "text to convert", "mode": "'encode' or 'decode'"}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        text = str(parameters.get("text", ""))
        mode = str(parameters.get("mode", "encode")).lower()
        if not text:
            return ToolResult.fail(error="missing_parameter", message="No text provided.")
        try:
            if mode == "encode":
                result = b64.b64encode(text.encode("utf-8")).decode("ascii")
            elif mode == "decode":
                result = b64.b64decode(text.encode("ascii")).decode("utf-8")
            else:
                return ToolResult.fail(error="invalid_parameter", message="mode must be 'encode' or 'decode'.")
            return ToolResult.ok(data=result, message=result)
        except Exception as e:
            return ToolResult.fail(error="conversion_failed", message=str(e))


class JSONFormatterTool(Tool):
    name = "format_json"
    description = "Pretty-print or validate a JSON string."
    parameters = {"text": "a JSON string"}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        text = str(parameters.get("text", ""))
        if not text:
            return ToolResult.fail(error="missing_parameter", message="No JSON text provided.")
        try:
            parsed = json.loads(text)
            pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
            return ToolResult.ok(data=pretty, message=pretty)
        except Exception as e:
            return ToolResult.fail(error="invalid_json", message=f"Invalid JSON: {e}")


class TextStatsTool(Tool):
    name = "text_stats"
    description = "Count characters, words, and lines in a block of text."
    parameters = {"text": "text to analyze"}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        text = str(parameters.get("text", ""))
        if not text:
            return ToolResult.fail(error="missing_parameter", message="No text provided.")
        stats = {
            "characters": len(text),
            "words": len(text.split()),
            "lines": len(text.splitlines()) or 1,
        }
        msg = f"{stats['characters']} characters, {stats['words']} words, {stats['lines']} lines."
        return ToolResult.ok(data=stats, message=msg)
