import ast  # Python Abstract Syntax Tree module for parsing and walking Python code

class MutableDefaultArgumentsRule:
    """Rule for detecting mutable default arguments in function definitions (GCS006)."""
    id = "GCS006"                  # Unique rule identifier for the Green Code Smell catalog
    name = "MutableDefaultArguments"  # Short display name used in reports and issue dictionaries
    description = "Detects functions that use mutable default arguments."
    severity = "Medium"            # Impact severity level for this code smell

    def check(self, tree):
        """
        Run the Mutable Default Arguments detection rule on the given AST.
        
        Scans all function definitions for default argument values that are
        mutable types (list, dict, set), which can cause subtle bugs due to
        shared state between calls.
        
        Args:
            tree: The parsed AST of a Python file.
        
        Returns:
            A list of issue dictionaries describing functions with mutable defaults.
        """
        issues = []  # Accumulator for detected mutable default argument issues
        # Define the set of AST node types that represent mutable default values
        # These are list literals ([]), dict literals ({}), and set literals ({x, y})
        mutable_types = (ast.List, ast.Dict, ast.Set)

        # Walk every node in the AST to find function definitions
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Iterate over all default argument values for this function's parameters
                for default in node.args.defaults:
                        # Check if the default value is a mutable type (list, dict, or set)
                        if isinstance(default, mutable_types):
                            # Report this function as having a mutable default argument
                            issues.append({
                                "rule": self.name,             # Rule name for grouping in reports
                                "lineno": node.lineno,         # Starting line number of the function
                                "end_lineno": node.end_lineno, # Ending line number of the function
                                "message": f"Function '{node.name}' has a mutable default argument. Consider using None and initializing inside the function.",
                            })
        return issues  # Return all detected mutable default argument issues