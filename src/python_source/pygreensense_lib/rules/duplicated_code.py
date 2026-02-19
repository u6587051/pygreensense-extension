import ast                           # Python Abstract Syntax Tree module for parsing and walking Python code
from collections import defaultdict  # Dictionary subclass that provides a default value for missing keys
from difflib import SequenceMatcher  # String similarity comparison using longest common subsequences

class DuplicatedCodeRule:
    """Rule for detecting duplicated code blocks via AST normalization and similarity matching (GCS003)."""
    id = "GCS003"                  # Unique rule identifier for the Green Code Smell catalog
    name = "DuplicatedCode"        # Short display name used in reports and issue dictionaries
    description = "Detects duplicated code blocks based on similarity."
    severity = "Medium"            # Impact severity level for this code smell
    
    def __init__(self, similarity_threshold=0.85, min_statements=3, check_within_functions=True, check_between_functions=True):
        """
        Args:
            similarity_threshold: Minimum similarity ratio (0.0 to 1.0) to consider as duplicate
            min_statements: Minimum number of statements in a code block to check for duplication
            check_within_functions: Check for duplicated code within the same function
            check_between_functions: Check for duplicated code between different functions
        """
        self.similarity_threshold = similarity_threshold      # Store the minimum similarity ratio threshold
        self.min_statements = min_statements                  # Store the minimum block size for analysis
        self.check_within_functions = check_within_functions  # Flag: enable intra-function duplication check
        self.check_between_functions = check_between_functions  # Flag: enable inter-function duplication check
    
    def _normalize_code(self, node):
        """
        Normalize an AST node into a hashable tuple for structural comparison.
        Replaces variable names with 'VAR' and constants with type placeholders
        so that structurally identical code with different names is recognized as similar.
        
        Args:
            node: An AST node, list, or primitive value.
        
        Returns:
            A normalized tuple representation of the structure.
        """
        # Handle ast.Name nodes (variable references): normalize to generic "VAR"
        # so that structurally identical code with different variable names matches
        if isinstance(node, ast.Name):
            return "VAR"
        # Handle ast.Constant nodes (literals): normalize to type placeholder
        # e.g., integer 42 → "CONST_int", string "hello" → "CONST_str"
        elif isinstance(node, ast.Constant):
            return f"CONST_{type(node.value).__name__}"
        # Handle list nodes: recursively normalize each element
        elif isinstance(node, list):
            return tuple(self._normalize_code(item) for item in node)
        # Handle general AST nodes: extract class name and recursively normalize fields
        elif isinstance(node, ast.AST):
            result = [node.__class__.__name__]  # Start with the AST node type name
            for field, value in ast.iter_fields(node):
                # Skip positional metadata and context fields (not structurally meaningful)
                if field in ('lineno', 'col_offset', 'end_lineno', 'end_col_offset', 'ctx'):
                    continue
                # Recursively normalize each field value
                result.append((field, self._normalize_code(value)))
            return tuple(result)  # Return as a hashable tuple
        # For primitive values (str, int, etc.), return as-is
        else:
            return node
    
    def _calculate_similarity(self, code1, code2):
        """
        Calculate the similarity ratio between two normalized code blocks.
        Uses SequenceMatcher on the string representations of the normalized ASTs.
        
        Args:
            code1: First normalized code block (tuple).
            code2: Second normalized code block (tuple).
        
        Returns:
            A float between 0.0 and 1.0 representing the similarity ratio.
        """
        # Convert both normalized tuples to strings for SequenceMatcher comparison
        str1 = str(code1)
        str2 = str(code2)
        # Return the similarity ratio (0.0 = completely different, 1.0 = identical)
        return SequenceMatcher(None, str1, str2).ratio()
    
    def _extract_all_functions(self, tree):
        """
        Extract all function/async function definitions from an AST.
        Only includes functions whose body has at least `min_statements` statements.
        Each function is returned with its name, line range, statement count,
        normalized body, and raw AST body.
        
        Args:
            tree: The parsed AST to scan.
        
        Returns:
            A list of dicts with keys: 'name', 'lineno', 'end_lineno', 'statements',
            'normalized', and 'body'.
        """
        functions = []  # Accumulator for function info dictionaries
        # Walk every node in the AST to find function definitions
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Only include functions with enough statements to be worth checking
                if len(node.body) >= self.min_statements:
                    # Normalize the function body for structural comparison
                    normalized = tuple(self._normalize_code(stmt) for stmt in node.body)
                    # Store function metadata and normalized representation
                    functions.append({
                        'name': node.name,               # Function name
                        'lineno': node.lineno,           # Starting line number
                        'end_lineno': node.end_lineno,   # Ending line number
                        'statements': len(node.body),    # Number of top-level statements
                        'normalized': normalized,         # Normalized AST tuple for comparison
                        'body': node.body                # Raw AST body for block extraction
                    })
        return functions  # Return all qualifying function info dicts
    
    def _extract_code_blocks(self, statements, min_size, parent_name="module", parent_lineno=0):
        """
        Extract sliding-window code blocks of various sizes from a list of statements.
        Used for detecting duplicated code blocks within a single function.
        
        Args:
            statements: List of AST statement nodes.
            min_size: Minimum number of statements to form a block.
            parent_name: Name of the enclosing function/module for context.
            parent_lineno: Line number of the enclosing function for context.
        
        Returns:
            A list of block dicts with 'parent', 'parent_lineno', 'start_line',
            'end_line', 'statements', and 'normalized' keys.
        """
        blocks = []  # Accumulator for extracted code block dictionaries
        
        # Skip if there are not enough statements to form even one block
        if len(statements) < min_size:
            return blocks
        
        # Generate sliding windows of various sizes from the statement list.
        # Starting position: iterate from first statement to the last valid starting index.
        for i in range(len(statements) - min_size + 1):
            # Window size: from min_size up to min_size+4 (cap at remaining statements)
            for window_size in range(min_size, min(len(statements) - i + 1, min_size + 5)):
                # Extract a slice of statements forming this code block
                block = statements[i:i + window_size]
                # Normalize the block for structural comparison
                normalized = tuple(self._normalize_code(stmt) for stmt in block)
                
                # Store block metadata and normalized representation
                blocks.append({
                    'parent': parent_name,            # Name of the enclosing function/module
                    'parent_lineno': parent_lineno,   # Line number of the enclosing function
                    'start_line': block[0].lineno if hasattr(block[0], 'lineno') else 0,  # Block start line
                    'end_line': block[-1].lineno if hasattr(block[-1], 'lineno') else 0,  # Block end line
                    'statements': len(block),         # Number of statements in this block
                    'normalized': normalized           # Normalized AST tuple for comparison
                })
        
        return blocks  # Return all extracted code blocks
    
    def _check_function_to_function(self, functions):
        """
        Detect duplicated code between different functions by comparing their
        full normalized bodies. Groups similar functions and reports each group once.
        
        Args:
            functions: List of function info dicts from _extract_all_functions().
        
        Returns:
            A list of issue dicts for functions exceeding the similarity threshold.
        """
        issues = []                      # Accumulator for detected duplication issues
        compared = set()                 # Track already-compared function pairs to avoid duplicates
        similar_groups = defaultdict(list)  # Group similar functions together by a shared group key
        
        # Compare every pair of functions (i, j) where i < j to avoid redundant comparisons
        for i, func1 in enumerate(functions):
            for j, func2 in enumerate(functions):
                if i >= j:
                    continue  # Skip self-comparison and already-compared reverse pairs
                
                # Create a sorted pair key to ensure consistent deduplication
                pair_key = tuple(sorted([func1['name'], func2['name']]))
                if pair_key in compared:
                    continue  # Skip if this pair was already compared
                compared.add(pair_key)  # Mark this pair as compared
                
                # Calculate the structural similarity between the two functions' normalized bodies
                similarity = self._calculate_similarity(func1['normalized'], func2['normalized'])
                
                # If similarity exceeds the threshold, group these functions together
                if similarity >= self.similarity_threshold:
                    group_found = False  # Flag to track if an existing group was extended
                    # Search existing groups to see if either function is already in one
                    for group_key in list(similar_groups.keys()):
                        # Check if func1 is already in this group
                        if func1['name'] in [f['name'] for f in similar_groups[group_key]]:
                            # Add func2 to the same group if not already present
                            if func2 not in similar_groups[group_key]:
                                similar_groups[group_key].append(func2)
                            group_found = True
                            break
                        # Check if func2 is already in this group
                        elif func2['name'] in [f['name'] for f in similar_groups[group_key]]:
                            # Add func1 to the same group if not already present
                            if func1 not in similar_groups[group_key]:
                                similar_groups[group_key].append(func1)
                            group_found = True
                            break
                    
                    # If neither function was in an existing group, create a new group
                    if not group_found:
                        group_id = f"{func1['name']}_{func2['name']}"
                        similar_groups[group_id] = [func1, func2]
        
        # Track which functions have been reported to avoid duplicate issue reports
        reported_functions = set()
        # Generate issue reports for each similarity group
        for group_id, group in similar_groups.items():
            # Deduplicate functions within the group by name
            unique_funcs = {}
            for func in group:
                if func['name'] not in unique_funcs:
                    unique_funcs[func['name']] = func
            
            group = list(unique_funcs.values())  # Convert back to list after dedup
            
            # Only report groups with at least 2 distinct functions
            if len(group) >= 2:
                group_names = set(f['name'] for f in group)
                # Only report if none of these functions have been reported already
                if group_names.isdisjoint(reported_functions):
                    # Build descriptive function name strings with line info
                    func_names = [f"{f['name']}() (line {f['lineno']}, {f['statements']} statements)" for f in group]
                    
                    # Calculate the average similarity across all pairs in the group
                    similarities = []
                    for i, func1 in enumerate(group):
                        for j, func2 in enumerate(group):
                            if i < j:
                                sim = self._calculate_similarity(func1['normalized'], func2['normalized'])
                                similarities.append(sim)
                    
                    # Compute average similarity (or 0 if no pairs)
                    avg_similarity = sum(similarities) / len(similarities) if similarities else 0
                    
                    # Create the issue report for this group of similar functions
                    issues.append({
                        "rule": self.name,             # Rule name for grouping in reports
                        "lineno": group[0]['lineno'],  # Line of the first function in the group
                        "end_lineno": group[0]['end_lineno'],  # End line of the first function
                        "message": f"Similar function implementations (similarity: {avg_similarity:.1%}): {', '.join(func_names)}. Consider refactoring into a single function."
                    })
                    
                    # Mark all functions in this group as reported
                    reported_functions.update(group_names)
        
        return issues  # Return all inter-function duplication issues
    
    def _check_within_functions(self, functions):
        """
        Detect duplicated code blocks within each individual function.
        Compares non-overlapping sliding-window blocks and reports the first
        duplicate pair found per function.
        
        Args:
            functions: List of function info dicts from _extract_all_functions().
        
        Returns:
            A list of issue dicts for within-function duplications.
        """
        issues = []  # Accumulator for within-function duplication issues
        
        # Analyze each function individually for internal code duplication
        for func in functions:
            # A function needs at least 2× min_statements to possibly contain duplicates
            if func['statements'] < self.min_statements * 2:
                continue  # Not enough statements for any duplicated pair
            
            # Extract all sliding-window code blocks from this function's body
            blocks = self._extract_code_blocks(
                func['body'],              # The function's AST statement list
                self.min_statements,       # Minimum block size
                f"function:{func['name']}", # Parent context label
                func['lineno']             # Parent starting line
            )
            
            # Track reported block pairs to avoid duplicate issue reports
            reported_pairs = set()
            
            # Compare every pair of blocks within this function
            for i, block1 in enumerate(blocks):
                for j, block2 in enumerate(blocks):
                    if i >= j:
                        continue  # Skip self-comparison and reverse pairs
                    
                    # Skip overlapping blocks (they share lines and aren't true duplicates)
                    if not (block1['end_line'] < block2['start_line'] or block2['end_line'] < block1['start_line']):
                        continue  # Blocks overlap - not a valid comparison
                    
                    # Create a unique sortable key for this pair of blocks
                    pair_key = (min(block1['start_line'], block2['start_line']), 
                               max(block1['start_line'], block2['start_line']))
                    
                    if pair_key in reported_pairs:
                        continue  # Already reported this pair
                    
                    # Calculate structural similarity between the two code blocks
                    similarity = self._calculate_similarity(block1['normalized'], block2['normalized'])
                    
                    # If similarity exceeds the threshold, report this as duplicated code
                    if similarity >= self.similarity_threshold:
                        issues.append({
                            "rule": self.name,             # Rule name for grouping in reports
                            "lineno": block1['start_line'],  # Start line of the first block
                            "end_lineno": block1['end_line'],  # End line of the first block
                            "message": f"Duplicated code block in function '{func['name']}' (similarity: {similarity:.1%}): lines {block1['start_line']}-{block1['end_line']} and {block2['start_line']}-{block2['end_line']} ({block1['statements']} statements). Consider extracting to a separate function."
                        })
                        reported_pairs.add(pair_key)  # Mark this pair as reported
                        # Only report the first duplicate found in this function to avoid noise
                        break
                # Break outer loop too if a duplicate was found (one report per function)
                if reported_pairs:
                    break
        
        return issues  # Return all within-function duplication issues
    
    def check(self, tree):
        """
        Run the duplicated code detection rule on the given AST.
        Checks for both between-function and within-function duplications
        based on the configuration flags.
        
        Args:
            tree: The parsed AST of a Python file.
        
        Returns:
            A list of issue dictionaries describing detected duplications.
        """
        issues = []  # Accumulator for all duplication issues
        
        # Extract all qualifying functions from the AST
        functions = self._extract_all_functions(tree)
        
        # Check for similar whole-function implementations (inter-function comparison)
        if self.check_between_functions and len(functions) >= 2:
            issues.extend(self._check_function_to_function(functions))
        
        # Check for duplicated code blocks within individual functions (intra-function comparison)
        if self.check_within_functions:
            issues.extend(self._check_within_functions(functions))
        
        return issues  # Return all detected duplication issues