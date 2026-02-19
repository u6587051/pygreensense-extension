import ast  # Python Abstract Syntax Tree module for parsing and walking Python code

class GodClassRule:
    """Rule for detecting the God Class anti-pattern (GCS002)."""
    id = "GCS002"                  # Unique rule identifier for the Green Code Smell catalog
    name = "GodClass"              # Short display name used in reports and issue dictionaries
    description = "Detects classes that have too many responsibilities (God Class anti-pattern)."
    severity = "High"              # Impact severity level for this code smell
    
    def __init__(self, max_methods=10, max_cc=35, max_loc=100):
        """
        Initialize the GodClassRule with configurable thresholds.
        
        Args:
            max_methods: Maximum number of methods before flagging (default: 10).
            max_cc: Maximum total cyclomatic complexity before flagging (default: 35).
            max_loc: Maximum lines of code before flagging (default: 100).
        """
        self.max_methods = max_methods  # Store the maximum allowed method count threshold
        self.max_cc = max_cc            # Store the maximum allowed total cyclomatic complexity threshold
        self.max_loc = max_loc          # Store the maximum allowed lines of code threshold

    def calculate_complexity(self, node):
        """
        Calculate the cyclomatic complexity for an AST node (method or class).
        Counts decision points: if, while, for, except, with, assert, boolean ops,
        and comprehension filter clauses.
        
        Args:
            node: An AST node to measure.
        
        Returns:
            An integer representing the cyclomatic complexity (base = 1).
        """
        complexity = 1  # Base complexity: every function starts with 1 execution path
        
        # Walk all child nodes to find decision points that add execution paths
        for child in ast.walk(node):
            # Branching statements: if, while, for, async for each add one path
            if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                complexity += 1
            # Exception handlers add a path for each except clause
            elif isinstance(child, ast.ExceptHandler):
                complexity += 1
            # Context managers (with/async with) may raise exceptions, adding a path
            elif isinstance(child, (ast.With, ast.AsyncWith)):
                complexity += 1
            # Assert statements add a path (assertion can fail)
            elif isinstance(child, ast.Assert):
                complexity += 1
            # Boolean operations (and/or): each additional operand adds a short-circuit path
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1  # N values = N-1 additional paths
            # Comprehension filter clauses (if conditions inside list/dict/set comprehensions)
            elif isinstance(child, ast.comprehension):
                complexity += len(child.ifs)  # Each 'if' in the comprehension adds a path
        
        return complexity  # Return the total cyclomatic complexity count

    def check(self, tree):
        """
        Run the God Class detection rule on the given AST.
        
        Examines each class for excessive method count, total cyclomatic complexity,
        and line count. Reports classes that exceed any configured threshold.
        
        Args:
            tree: The parsed AST of a Python file.
        
        Returns:
            A list of issue dictionaries describing detected God Classes.
        """
        issues = []  # Accumulator for detected God Class issues
        # Walk every node in the AST to find class definitions
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Extract all method definitions (FunctionDef nodes) from the class body
                methods = [n for n in node.body if isinstance(n, ast.FunctionDef)]
                method_count = len(methods)  # Count total methods in this class
                
                # Calculate the cumulative cyclomatic complexity across all methods
                total_complexity = 0
                for method in methods:
                    total_complexity += self.calculate_complexity(method)
                
                # Calculate the total line count of the class definition
                if hasattr(node, 'end_lineno') and hasattr(node, 'lineno'):
                    line_count = node.end_lineno - node.lineno + 1  # Inclusive line range
                else:
                    line_count = 0  # Fallback if line number info is unavailable
                
                # Check each threshold and collect violation messages
                problems = []
                if method_count > self.max_methods:
                    problems.append(f"{method_count} methods (max: {self.max_methods})")
                if total_complexity > self.max_cc:
                    problems.append(f"complexity {total_complexity} (max: {self.max_cc})")
                if line_count > self.max_loc:
                    problems.append(f"{line_count} lines (max: {self.max_loc})")
                
                # If any threshold was exceeded, report this class as a God Class
                if problems:
                    issues.append({
                        "rule": self.name,             # Rule name for grouping in reports
                        "lineno": node.lineno,         # Starting line number of the class
                        "end_lineno": node.end_lineno, # Ending line number of the class
                        "message": f"Class '{node.name}' is a God Class: {', '.join(problems)}. Consider refactoring by extract into sub class.",
                    })
        
        return issues  # Return all detected God Class issues