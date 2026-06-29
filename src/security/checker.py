import ast
import os
import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger("aion.security.checker")


class SecurityViolation:
    def __init__(self, type: str, message: str, severity: str = "high"):
        self.type = type
        self.message = message
        self.severity = severity


class AIONAntivirus:
    """
    Scans Python source code for malicious patterns, suspicious imports,
    and potentially dangerous system calls before activation.
    """

    # Dangerous functions and modules
    DANGEROUS_IMPORTS = {
        "os",
        "subprocess",
        "sys",
        "shutil",
        "pickle",
        "marshal",
        "builtins",
        "importlib",
        "socket",
        "urllib",
        "requests",
    }

    DANGEROUS_FUNCTIONS = {
        "eval",
        "exec",
        "compile",
        "__import__",
        "getattr",
        "setattr",
    }

    @staticmethod
    async def scan_file(file_path: str) -> Tuple[bool, List[Dict[str, str]]]:
        """
        Performs static analysis on a python file.
        Returns (is_safe, list_of_violations).
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                code = f.read()

            tree = ast.parse(code)
            violations = []

            for node in ast.walk(tree):
                # Check for suspicious imports
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in AIONAntivirus.DANGEROUS_IMPORTS:
                            violations.append(
                                {
                                    "type": "Suspicious Import",
                                    "message": f"Importing sensitive module: {alias.name}",
                                    "severity": "medium",
                                }
                            )

                if isinstance(node, ast.ImportFrom):
                    if node.module in AIONAntivirus.DANGEROUS_IMPORTS:
                        violations.append(
                            {
                                "type": "Suspicious Import",
                                "message": f"Importing from sensitive module: {node.module}",
                                "severity": "medium",
                            }
                        )

                # Check for dangerous function calls
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id in AIONAntivirus.DANGEROUS_FUNCTIONS:
                            violations.append(
                                {
                                    "type": "Dangerous Call",
                                    "message": f"Call to dangerous function: {node.func.id}",
                                    "severity": "high",
                                }
                            )

                    # Check for shell=True in subprocess
                    if isinstance(node.func, ast.Attribute) and node.func.attr in [
                        "run",
                        "Popen",
                        "call",
                    ]:
                        for keyword in node.keywords:
                            if (
                                keyword.arg == "shell"
                                and isinstance(keyword.value, ast.Constant)
                                and keyword.value.value is True
                            ):
                                violations.append(
                                    {
                                        "type": "Shell Injection Risk",
                                        "message": "subprocess call with shell=True detected",
                                        "severity": "critical",
                                    }
                                )

            # If it passes high/critical threshold, it's considered "safe" for auto-enabling
            is_safe = not any(v["severity"] in ["high", "critical"] for v in violations)
            return is_safe, violations

        except Exception as e:
            return False, [
                {
                    "type": "Syntax/Parse Error",
                    "message": str(e),
                    "severity": "critical",
                }
            ]

    @staticmethod
    async def scan_directory(directory_path: str) -> Dict[str, List[Dict[str, str]]]:
        """Scans all python files in a directory."""
        all_violations = {}
        for root, _, files in os.walk(directory_path):
            for file in files:
                if file.endswith(".py") and ".venv" not in root:
                    path = os.path.join(root, file)
                    _, violations = await AIONAntivirus.scan_file(path)
                    if violations:
                        all_violations[path] = violations
        return all_violations
