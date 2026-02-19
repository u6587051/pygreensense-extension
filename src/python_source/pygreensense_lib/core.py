import ast          # Python Abstract Syntax Tree module for parsing Python source code
from pathlib import Path  # Object-oriented filesystem path handling

def analyze_file(file_path, rules, project_root=None):
    """
    Analyze a single Python file for code smells using the provided rules.
    
    Reads the file, parses it into an AST, and runs each rule's check method.
    Special handling is applied for DeadCodeRule which needs project context.
    
    Args:
        file_path: Path to the Python file to analyze.
        rules: List of rule instances (e.g., GodClassRule, LongMethodRule) to apply.
        project_root: Optional root directory for project-wide rules like DeadCodeRule.
    
    Returns:
        A list of issue dictionaries, each containing 'rule', 'message', 'lineno', etc.
    """
    # Read the file content and parse it into an Abstract Syntax Tree
    code = Path(file_path).read_text()
    tree = ast.parse(code)
    # Accumulator for all issues found by all rules
    issues = []

    # Apply each rule to the parsed AST
    for rule in rules:
        # DeadCodeRule requires special project-level context for cross-file analysis
        if rule.__class__.__name__ == 'DeadCodeRule':
            # Set the project root to the file's parent directory for single-file mode
            rule.project_root = str(Path(file_path).parent)
            # Enable single-file mode so DeadCodeRule only checks within this file
            rule.single_file_mode = True
            # Set the target file path so DeadCodeRule knows which file to analyze
            rule.target_file = str(Path(file_path).resolve())
            # Run the rule's check method against the AST
            rule_issues = rule.check(tree)
            # Attach the file path to each issue for identification in reports
            for issue in rule_issues:
                issue['file'] = file_path
            # Add all issues from this rule to the master list
            issues.extend(rule_issues)
        else:
            # Standard rules (GodClass, LongMethod, etc.) just need the AST
            issues.extend(rule.check(tree))

    # Return all collected issues from all rules
    return issues

def analyze_project(project_path, rules):
    """
    Analyze an entire project directory for code smells.
    
    Iterates over all Python files (excluding venv, __pycache__, etc.) and applies
    each rule. DeadCodeRule is handled specially via its check_project() method
    which performs cross-file unused definition analysis.
    
    Args:
        project_path: Path to the project root directory.
        rules: List of rule instances to apply across the project.
    
    Returns:
        A list of issue dictionaries from all files combined.
    """
    # Accumulator for all issues found across all project files
    issues = []
    
    # Iterate over each rule to apply project-wide analysis
    for rule in rules:
        # DeadCodeRule uses a special project-wide check for cross-file analysis
        if rule.__class__.__name__ == 'DeadCodeRule':
            # Set the project root so DeadCodeRule can scan all files
            rule.project_root = str(project_path)
            # Use check_project() instead of check() for cross-file dead code detection
            rule_issues = rule.check_project()
            # DeadCodeRule's check_project() already attaches 'file' field to each issue
            issues.extend(rule_issues)
        else:
            # For standard rules, iterate over every .py file in the project tree
            py_files = list(Path(project_path).rglob("*.py"))
            # Directories to skip: virtual environments, caches, git, node_modules, etc.
            exclude_dirs = {'venv', '.venv', 'env', '__pycache__', '.git', 'node_modules', '.pytest_cache', '.tox'}
            
            # Process each Python file individually
            for py_file in py_files:
                # Skip files whose parent directories match any excluded directory name
                if not any(parent.name in exclude_dirs for parent in py_file.parents):
                    try:
                        # Read the Python source code from the file
                        code = py_file.read_text()
                        # Parse the source code into an Abstract Syntax Tree
                        tree = ast.parse(code)
                        # Run the current rule's check method against the AST
                        rule_issues = rule.check(tree)
                        # Attach the file path to each issue for report identification
                        for issue in rule_issues:
                            issue['file'] = str(py_file)
                        # Add all issues from this file to the master list
                        issues.extend(rule_issues)
                    except Exception:
                        # Silently skip files that fail to parse (syntax errors, encoding issues)
                        pass
    
    # Return all collected issues from all files and all rules
    return issues

def code_info(file_path):
    """
    Extract basic code metrics from a Python file.
    
    Parses the file into an AST and counts the total number of lines,
    function definitions, and class definitions.
    
    Args:
        file_path: Path to the Python file to inspect.
    
    Returns:
        A dictionary with keys 'lines', 'functions', and 'classes' (all integers).
    """
    # Read the entire Python file content as a string
    code = Path(file_path).read_text()
    # Parse the source code into an Abstract Syntax Tree for node traversal
    tree = ast.parse(code)
    # Build and return a dictionary of basic code metrics
    return {
        # Count total lines by splitting source into individual lines
        "lines": len(code.splitlines()),
        # Count function definitions by walking the AST and filtering FunctionDef nodes
        "functions": sum(isinstance(node, ast.FunctionDef) for node in ast.walk(tree)),
        # Count class definitions by walking the AST and filtering ClassDef nodes
        "classes": sum(isinstance(node, ast.ClassDef) for node in ast.walk(tree)),
    }