import sys
import io
import pandas as pd
import numpy as np


class CodeExecutor:
    def __init__(self):
        self.safe_builtins = {
            "abs": abs,
            "min": min,
            "max": max,
            "sum": sum,
            "len": len,
            "range": range,
            "enumerate": enumerate,
            "zip": zip,
            "int": int,
            "float": float,
            "str": str,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "sorted": sorted,
            "reversed": reversed,
            "print": print,
        }

    def execute(self, code: str) -> str:
        try:
            safe_globals = {
                "__builtins__": self.safe_builtins,
                "math": __import__("math"),
                "numpy": np,
                "np": np,
                "pandas": pd,
                "pd": pd,
            }
            local_vars = {}

            # Redirect stdout to capture prints
            old_stdout = sys.stdout
            redirected_output = io.StringIO()
            sys.stdout = redirected_output

            try:
                exec(code, safe_globals, local_vars)
            finally:
                sys.stdout = old_stdout

            if "result" not in local_vars:
                return "Error: Code must assign final output to variable 'result'"

            output = redirected_output.getvalue()
            result = local_vars["result"]

            final_msg = f"Execution successful.\n"
            if output:
                final_msg += f"Stdout: {output}\n"
            final_msg += f"Result: {result}"
            return final_msg

        except Exception as e:
            return f"Error executing code: {type(e).__name__}: {str(e)}"
