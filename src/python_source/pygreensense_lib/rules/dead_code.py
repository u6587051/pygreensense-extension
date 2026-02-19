import ast              # Python Abstract Syntax Tree module for parsing and walking Python code
from pathlib import Path  # Object-oriented filesystem path handling for recursive file discovery

class DeadCodeRule:
    """Rule for detecting unreachable code and unused definitions (GCS005)."""
    id = "GCS005"                  # Unique rule identifier for the Green Code Smell catalog
    name = "DeadCode"              # Short display name used in reports and issue dictionaries
    description = "Detects unreachable code and unused definitions."
    severity = "Medium"            # Impact severity level for this code smell
    
    def __init__(self, project_root=None):
        """
        Initialize the DeadCodeRule.
        
        Args:
            project_root: Optional path to the project root for cross-file analysis.
        """
        self.project_root = project_root   # Root directory for project-wide analysis mode
        self.all_definitions = {}  # Maps file_path -> {name: (type, lineno, end_lineno)} for all files
        self.all_usages = {}       # Maps file_path -> set of referenced names for all files
        self.all_imports = {}      # Maps file_path -> set of imported names for all files
        self.is_project_mode = False  # Flag indicating whether we're in single-file or project mode
    
    def check(self, tree, file_path=None):
        """
        Check a single file's AST for dead code issues.
        
        Detects unused definitions (functions, classes, variables) that are never
        referenced within the file, and unreachable code after return/raise/break.
        
        Args:
            tree: The parsed AST of the file.
            file_path: Optional file path for issue reporting.
        
        Returns:
            A list of issue dictionaries with 'rule', 'lineno', 'end_lineno', and 'message'.
        """
        issues = []  # Accumulator for detected dead code issues
        
        # --- Phase 1: Detect unused definitions (functions, classes, variables) ---
        # Collect all definitions (def, class, assignment) declared in the file
        defined = self._collect_definitions(tree)
        # Collect all name references (loads) used in the file
        used = self._collect_usage(tree)
        # Collect all imported names to avoid false positives on re-exports
        imports = self._collect_imports(tree)
        
        # Compare definitions against usages/imports to find unused ones
        self._check_unused(defined, used, imports, issues)
        
        # --- Phase 2: Detect unreachable code after terminators ---
        self._check_unreachable(tree, issues)
        
        return issues  # Return all detected dead code issues
    
    def check_project(self):
        """
        Analyze an entire project for dead code across all Python files.
        
        Collects definitions and usages from every .py file in the project,
        then cross-references to find definitions that are never used anywhere.
        Also checks for unreachable code in each file.
        
        Returns:
            A list of issue dictionaries including the 'file' field for each issue.
        """
        self.is_project_mode = True  # Enable project mode for file-level issue reporting
        all_issues = []  # Accumulator for all issues found across the entire project
        
        # Step 1: Discover all Python files in the project directory tree
        py_files = list(Path(self.project_root).rglob("*.py"))
        
        # If no Python files found, return empty results
        if not py_files:
            return all_issues
        
        # Step 1b: Parse each file and collect definitions, usages, and imports
        for py_file in py_files:
            try:
                # Read and parse the Python source file
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    tree = ast.parse(content)
                    
                file_str = str(py_file)  # Convert Path to string for use as dictionary key
                # Collect all definitions (functions, classes, variables) from this file
                self.all_definitions[file_str] = self._collect_definitions(tree)
                # Collect all name references (usages) from this file
                self.all_usages[file_str] = self._collect_usage(tree)
                # Collect all imported names from this file
                self.all_imports[file_str] = self._collect_imports(tree)
            except Exception:
                # Skip files that can't be parsed (syntax errors, encoding issues)
                continue
        
        # Step 2: Cross-reference definitions against usages across ALL files
        for file_path, definitions in self.all_definitions.items():
            for name, (def_type, lineno, end_lineno) in definitions.items():
                # Skip private/dunder names (e.g., __init__, _helper) - they're intentionally scoped
                if name.startswith('_'):
                    continue
                
                # Check if this name is referenced or imported in ANY file across the project
                if not self._is_used_anywhere(name, file_path):
                    # Name is defined but never used anywhere - report as dead code
                    all_issues.append({
                        "rule": self.name,         # Rule name for grouping in reports
                        "lineno": lineno,          # Starting line of the unused definition
                        "end_lineno": end_lineno,  # Ending line of the unused definition
                        "file": file_path,         # File where the unused definition exists
                        "message": f"Unused {def_type} '{name}' is never referenced. Suggest removing it."
                    })
        
        # Step 3: Check for unreachable code in each file independently
        for py_file in py_files:
            try:
                # Re-parse each file to check for unreachable code blocks
                with open(py_file, 'r', encoding='utf-8') as f:
                    tree = ast.parse(f.read())
                    file_str = str(py_file)
                    # Check for unreachable code, passing the file path for issue reporting
                    self._check_unreachable(tree, all_issues, file_str)
            except Exception:
                continue  # Skip files that can't be parsed
        
        return all_issues  # Return all detected dead code issues across the project
    
    def _collect_definitions(self, tree):
        """
        Collect all top-level function, class, and variable definitions from an AST.
        
        Args:
            tree: The parsed AST to scan.
        
        Returns:
            A dict mapping name -> (type_str, lineno, end_lineno).
        """
        definitions = {}  # Dictionary mapping name -> (type_str, lineno, end_lineno)
        
        # Walk every node in the AST to find definitions at any scope level
        for node in ast.walk(tree):
            # Capture function definitions: def func_name():
            if isinstance(node, ast.FunctionDef):
                definitions[node.name] = ('function', node.lineno, node.end_lineno)
            
            # Capture class definitions: class ClassName:
            elif isinstance(node, ast.ClassDef):
                definitions[node.name] = ('class', node.lineno, node.end_lineno)
            
            # Capture variable assignments: var_name = value
            elif isinstance(node, ast.Assign):
                # Check each assignment target (handles multiple assignment like a = b = 1)
                for target in node.targets:
                    # Only capture simple name assignments (not tuple/list unpacking or attribute assignments)
                    if isinstance(target, ast.Name):
                        definitions[target.id] = ('variable', target.lineno, target.end_lineno)
        
        return definitions  # Return all collected definitions
    
    def _collect_usage(self, tree):
        """
        Collect all name references (loads) from an AST.
        Includes direct name access, attribute access, and function calls.
        
        Args:
            tree: The parsed AST to scan.
        
        Returns:
            A set of name strings that are referenced/used in the code.
        """
        used = set()  # Set of name strings that are referenced/used in the code
        
        # Walk every node in the AST to find name references
        for node in ast.walk(tree):
            # Direct name references in Load context (reading a variable's value)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used.add(node.id)  # Add the variable name to the used set
            
            # Attribute access: obj.attr or obj.method - tracks the attribute name
            elif isinstance(node, ast.Attribute):
                used.add(node.attr)  # Add the attribute/method name to the used set

            # Function/method calls: tracks the called function name
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    # Direct function call: func_name()
                    used.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    # Method call: obj.method_name() - track the method name
                    used.add(node.func.attr)
        
        return used  # Return all collected name references
    
    def _collect_imports(self, tree):
        """
        Collect all imported names from an AST (both 'import X' and 'from X import Y').
        Uses alias names when present.
        
        Args:
            tree: The parsed AST to scan.
        
        Returns:
            A set of imported name strings.
        """
        imports = set()  # Set of imported name strings
        
        # Walk every node in the AST to find import statements
        for node in ast.walk(tree):
            # Handle "from X import Y" and "from X import Y as Z" statements
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    # Use the alias name if provided (import Y as Z → "Z"), otherwise the original name
                    imports.add(alias.asname if alias.asname else alias.name)
            
            # Handle "import X" and "import X as Y" statements
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    # Use the alias name if provided (import X as Y → "Y"), otherwise the original name
                    imports.add(alias.asname if alias.asname else alias.name)
        
        return imports  # Return all collected imported names
    
    def _is_used_anywhere(self, name, file_path):
        """
        Check if a name is referenced or imported in any file across the project.
        
        Args:
            name: The definition name to look for.
            file_path: The file where the definition originated (for context).
        
        Returns:
            True if the name appears in any file's usages or imports.
        """
        # Search all files' usage sets for a reference to this name
        for file_usages in self.all_usages.values():
            if name in file_usages:
                return True  # Name is referenced somewhere in the project
        
        # Search all files' import sets for an import of this name
        for file_imports in self.all_imports.values():
            if name in file_imports:
                return True  # Name is imported somewhere in the project
        
        return False  # Name is never referenced or imported anywhere
    
    def _check_unused(self, defined, used, imports, issues):
        """
        Identify unused definitions that are never referenced or imported.
        Skips names starting with '_' (private/dunder) and imported names.
        
        Args:
            defined: Dict of definitions {name: (type, lineno, end_lineno)}.
            used: Set of referenced names.
            imports: Set of imported names.
            issues: List to append found issues to (modified in place).
        """
        # Iterate over each defined name and check if it's used or imported
        for name, (def_type, lineno, end_lineno) in defined.items():
            # Skip private/dunder names (e.g., __init__, _helper) - convention says they're scoped
            if name.startswith('_'):
                continue
            
            # Skip names that were imported - they might be re-exported for external use
            if name in imports:
                continue
            
            # If the name is not found in the usage set, it's unused dead code
            if name not in used:
                issues.append({
                    "rule": self.name,         # Rule name for grouping in reports
                    "lineno": lineno,          # Starting line of the unused definition
                    "end_lineno": end_lineno,
                    "message": f"Unused {def_type} '{name}' is never referenced. Suggest removing it."
                })
    
    def _check_unreachable(self, tree, issues, file_path=None):
        """
        Check for unreachable code after control flow terminators (return, raise, break, continue).
        Inspects function bodies, if/else blocks, except/finally handlers and loop bodies.
        
        Args:
            tree: The parsed AST to scan.
            issues: List to append found issues to (modified in place).
            file_path: Optional file path string for project-mode issue reporting.
        """
        # Walk every node in the AST to find compound statements that contain code bodies
        for node in ast.walk(tree):
            # Check function definitions, loops, if/else, with, and try/except blocks
            if isinstance(node, (ast.FunctionDef, ast.For, ast.While, ast.If, ast.With, ast.Try)):
                # Check the main body of the compound statement for unreachable code
                if hasattr(node, 'body'):
                    self._check_body_reachability(node.body, issues, file_path)
                
                # Check the else/elif blocks (used by for/while/if/try)
                if hasattr(node, 'orelse') and node.orelse:
                    self._check_body_reachability(node.orelse, issues, file_path)
                
                # Check individual except handler bodies (try/except blocks)
                if hasattr(node, 'handlers'):
                    for handler in node.handlers:
                        self._check_body_reachability(handler.body, issues, file_path)
                
                # Check the finally block body (try/finally blocks)
                if hasattr(node, 'finalbody') and node.finalbody:
                    self._check_body_reachability(node.finalbody, issues, file_path)
    
    def _check_body_reachability(self, body, issues, file_path=None):
        """
        Check a list of statements for unreachable code after a control flow terminator.
        Reports only the first unreachable statement found in the sequence.
        
        Args:
            body: List of AST statement nodes to check.
            issues: List to append found issues to (modified in place).
            file_path: Optional file path string for project-mode issue reporting.
        """
        terminator_found = False   # Flag: have we encountered a control flow terminator?
        terminator_line = None     # Line number of the terminator statement
        
        # Iterate through each statement in the body sequentially
        for i, stmt in enumerate(body):
            # Check if the current statement is a control flow terminator (return, raise, break, etc.)
            if self._is_terminator(stmt):
                terminator_found = True        # Mark that a terminator was found
                terminator_line = stmt.lineno  # Record which line the terminator is on
            
            # If we already found a terminator, any subsequent non-docstring statement is unreachable
            elif terminator_found and not self._is_docstring(stmt, i):
                # Build the unreachable code issue dictionary
                issue = {
                    "rule": self.name,         # Rule name for grouping in reports
                    "lineno": stmt.lineno,     # Starting line of the unreachable code
                    "end_lineno": stmt.end_lineno,  # Ending line of the unreachable code
                    "message": f"Unreachable code after statement at line {terminator_line}. Consider removing it."
                }
                # In project mode, attach the file path for file-level issue tracking
                if file_path and self.is_project_mode:
                    issue["file"] = file_path
                issues.append(issue)  # Add the unreachable code issue to the list
                # Only report the first unreachable statement to avoid noisy output
                break
    
    def _is_terminator(self, stmt):
        """
        Determine if a statement terminates control flow.
        Recognizes return, raise, break, continue, and exit()/sys.exit() calls.
        
        Args:
            stmt: An AST statement node.
        
        Returns:
            True if the statement is a control flow terminator.
        """
        # Check for return statement: terminates function execution
        if isinstance(stmt, ast.Return):
            return True
        
        # Check for raise statement: terminates with an exception
        if isinstance(stmt, ast.Raise):
            return True
        
        # Check for break/continue: terminates loop iteration or loop entirely
        if isinstance(stmt, (ast.Break, ast.Continue)):
            return True
        
        # Check for exit()/quit()/sys.exit() calls: terminates the entire program
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            if isinstance(stmt.value.func, ast.Name):
                # Direct builtin calls: exit() or quit()
                if stmt.value.func.id in ['exit', 'quit']:
                    return True
            elif isinstance(stmt.value.func, ast.Attribute):
                # Attribute-based call: sys.exit() or os._exit()
                if stmt.value.func.attr == 'exit':
                    return True
        
        return False  # Statement does not terminate control flow
    
    def _is_docstring(self, stmt, index):
        """
        Check if a statement is a docstring (string constant at position 0).
        Used to avoid false-positive unreachable code reports on docstrings.
        
        Args:
            stmt: An AST statement node.
            index: The statement's index within its parent body.
        
        Returns:
            True if the statement is a docstring at the start of a block.
        """
        # A docstring is: the first statement (index 0) in a block,
        # that is an expression statement containing a string constant.
        # This check prevents false-positive "unreachable code" on docstrings
        # that appear at the start of functions/classes/modules.
        return (index == 0 and 
                isinstance(stmt, ast.Expr) and           # Must be an expression statement
                isinstance(stmt.value, ast.Constant) and  # Must contain a constant value
                isinstance(stmt.value.value, str))         # The constant must be a string