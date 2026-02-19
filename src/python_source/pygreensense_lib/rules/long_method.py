import ast  # Python Abstract Syntax Tree module for parsing and walking Python code

class LongMethodRule:
    """Rule for detecting methods that are too long or too complex (GCS004)."""
    id = "GCS004"                  # Unique rule identifier for the Green Code Smell catalog
    name = "LongMethod"            # Short display name used in reports and issue dictionaries
    description = "Detects methods that are too long based on LOC and cyclomatic complexity."
    severity = "Medium"            # Impact severity level for this code smell
    
    def __init__(self, max_loc=30, max_cc=10):
        """
        Initialize the LongMethodRule with configurable thresholds.
        
        Args:
            max_loc: Maximum lines of code per method before flagging (default: 30).
            max_cc: Maximum cyclomatic complexity per method before flagging (default: 10).
        """
        self.max_loc = max_loc  # Store the maximum allowed lines of code per method
        self.max_cc = max_cc    # Store the maximum allowed cyclomatic complexity per method

    def calculate_cyclomatic_complexity(self, node):
        """
        Calculate cyclomatic complexity of a function.
        CC = number of decision points + 1
        Decision points include: if, for, while, and, or, except, with
        """
        complexity = 1  # Base complexity: every function starts with 1 execution path
        
        # Walk all child nodes to find decision points that add execution paths
        for child in ast.walk(node):
            # Branching/looping statements: if, while, for, async for each add one path
            if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                complexity += 1
            # Exception handlers add a path for each except clause
            elif isinstance(child, ast.ExceptHandler):
                complexity += 1
            # Boolean operators (and, or): each additional operand adds a short-circuit path
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1  # N values = N-1 additional paths
            # Comprehensions (list/dict/set/generator): each 'if' filter adds a path
            elif isinstance(child, (ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)):
                for generator in child.generators:
                    complexity += len(generator.ifs)  # Count filter conditions in each generator
            # Context managers (with/async with) may raise exceptions, adding a path
            elif isinstance(child, (ast.With, ast.AsyncWith)):
                complexity += 1
        
        return complexity  # Return the total cyclomatic complexity count

    def count_loops(self, node):
        """
        Count the total number of loop constructs (for, while, async for) in a function.
        
        Args:
            node: An AST function node to inspect.
        
        Returns:
            An integer count of loop nodes found.
        """
        loop_count = 0  # Initialize loop counter
        # Walk all child nodes looking for loop constructs
        for child in ast.walk(node):
            if isinstance(child, (ast.For, ast.While, ast.AsyncFor)):
                loop_count += 1  # Increment for each loop found
        return loop_count  # Return the total number of loops

    def check(self, tree):
        """
        Run the Long Method detection rule on the given AST.
        
        Examines each function/async function for excessive LOC and cyclomatic
        complexity. Reports methods that exceed any configured threshold.
        
        Args:
            tree: The parsed AST of a Python file.
        
        Returns:
            A list of issue dictionaries describing detected long methods.
        """
        issues = []  # Accumulator for detected Long Method issues
        
        # Walk every node in the AST to find function definitions
        for node in ast.walk(tree):
            # Check both regular and async function definitions
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Calculate the lines of code (LOC) spanned by this function
                if hasattr(node, 'end_lineno') and hasattr(node, 'lineno'):
                    loc = node.end_lineno - node.lineno + 1  # Inclusive line range
                else:
                    loc = 0  # Fallback if line number info is unavailable
                
                # Calculate the cyclomatic complexity of this function
                cyclomatic = self.calculate_cyclomatic_complexity(node)
                
                # Count the number of loop constructs in this function
                loop_count = self.count_loops(node)
                
                # Check each threshold and collect violation messages
                problems = []
                if loc > self.max_loc:
                    problems.append(f"LOC: {loc} (max: {self.max_loc})")
                if cyclomatic > self.max_cc:
                    problems.append(f"Cyclomatic Complexity: {cyclomatic} (max: {self.max_cc})")
                
                # If any threshold was exceeded, report this method as a Long Method
                if problems:
                    issues.append({
                        "rule": self.name,             # Rule name for grouping in reports
                        "lineno": node.lineno,         # Starting line number of the function
                        "end_lineno": node.end_lineno, # Ending line number of the function
                        "message": f"Method '{node.name}' is too long: {', '.join(problems)}. Consider refactoring by extracting smaller methods.",
                    })
        
        return issues  # Return all detected Long Method issues