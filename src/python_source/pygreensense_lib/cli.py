import sys              # System-specific parameters and functions (e.g., sys.exit, sys.executable)
import argparse         # Command-line argument parsing library
from pathlib import Path  # Object-oriented filesystem path handling
from datetime import datetime  # Date and time utilities for timestamping reports
import subprocess       # Subprocess management for running target files during carbon tracking
import ast              # Abstract Syntax Tree module for parsing Python source code
import json             # JSON encoding/decoding for reading/writing history.json
import os               # Operating system interface for file existence checks and path manipulation

# Try to import from the installed package first, then fall back to relative imports.
# This dual-import pattern supports both installed-package mode and direct script execution.
try:
    from core import analyze_file                           # Core file analysis function (direct import)
    from rules.god_class import GodClassRule                # God Class detection rule (GCS002)
    from .rules.duplicated_code import DuplicatedCodeRule   # Duplicated Code detection rule (GCS003)
    from .rules.long_method import LongMethodRule           # Long Method detection rule (GCS004)
    from .rules.dead_code import DeadCodeRule               # Dead Code detection rule (GCS005)
    from .rules.mutable_default_arguments import MutableDefaultArgumentsRule  # Mutable Default Args rule (GCS006)
    from .core import analyze_project, analyze_file         # Core project-level and file-level analysis functions
    from .constants import BREAK_LINE_NO, KG_GRAMS, SEC_HOUR  # Shared constants for formatting and unit conversion
except ImportError:
    # Fallback: if the package is not installed, adjust sys.path and use relative imports
    import os
    # Add the grandparent directory to the module search path so relative imports resolve
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from .core import analyze_file                           # Core file analysis function (relative import)
    from .rules.god_class import GodClassRule                # God Class detection rule (GCS002)
    from .rules.duplicated_code import DuplicatedCodeRule    # Duplicated Code detection rule (GCS003)
    from .rules.long_method import LongMethodRule            # Long Method detection rule (GCS004)
    from .rules.dead_code import DeadCodeRule                # Dead Code detection rule (GCS005)
    from .rules.mutable_default_arguments import MutableDefaultArgumentsRule  # Mutable Default Args rule (GCS006)
    from .core import analyze_project, analyze_file          # Core project/file analysis functions
    from .constants import BREAK_LINE_NO, KG_GRAMS, SEC_HOUR  # Shared constants

# Attempt to import CodeCarbon for carbon emissions tracking
try:
    from codecarbon import EmissionsTracker  # CodeCarbon tracker for measuring CO2 emissions
    CODECARBON_AVAILABLE = True              # Flag indicating CodeCarbon is available
except ImportError:
    # CodeCarbon is not installed; disable carbon tracking and warn the user
    CODECARBON_AVAILABLE = False
    print("⚠️  Warning: codecarbon not installed. Carbon tracking disabled.")
    print("   Install with: pip install codecarbon\n")

def calculate_cosmic_cfp(file_path): # TODO: Can we not parse file again? using the same tree that already parsed?
    """
    Calculate COSMIC Function Points (CFP) from Python source code.
    Compliant with ISO/IEC 19761:2011 (COSMIC v4.0.2).
    
    Data movements:
    - E (Entry): User data input from external sources
    - X (Exit): Results output to external systems
    - R (Read): Data retrieval from persistent storage (DB, files)
    - W (Write): Data write to persistent storage (DB, files)
    """
    try:
        # Open and read the entire Python source file with UTF-8 encoding
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse the source code into an Abstract Syntax Tree for analysis
        tree = ast.parse(content)
        # Initialize the total COSMIC Function Point counter
        total_cfp = 0
        
        # TODO: Improve by move or variable in constans file

        # Pattern sets for classifying function calls into COSMIC data movement types.
        # Each set contains keywords that, when found in a function call name,
        # indicate a specific type of data movement.

        # Database/persistent-storage READ operation patterns (R movement)
        db_read_patterns = {
            'query', 'select', 'find', 'fetch', 'get', 'load', 'filter',
            'all', 'first', 'one', 'read', 'execute'
        }
        # Database/persistent-storage WRITE operation patterns (W movement)
        db_write_patterns = {
            'insert', 'update', 'delete', 'save', 'create', 'put',
            'commit', 'execute', 'upsert', 'bulk_write'
        }
        
        # User/external INPUT source patterns (E movement - Entry)
        entry_patterns = {
            'input', 'getline', 'stdin', 'request', 'parse_args', 'argv',
            'json', 'loads', 'yaml', 'parse', 'environ'
        }
        
        # User/external OUTPUT destination patterns (X movement - Exit)
        exit_patterns = {
            'print', 'write', 'return', 'render', 'jsonify', 'dump',
            'response', 'send', 'emit', 'stdout', 'stderr'
        }
        
        # File I/O READ patterns (R movement - persistent storage)
        file_read_patterns = {'open', 'read', 'load', 'pickle'}
        # File I/O WRITE patterns (W movement - persistent storage)
        file_write_patterns = {'open', 'write', 'dump', 'save', 'pickle'}

        # Extract all function/async function definitions from the AST.
        # Per ISO/IEC 19761, each function is treated as one Functional Process.
        functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        
        # If no functions found, treat the entire module as a single functional process
        if not functions:
            functions = [tree]

        # Iterate over each functional process (function) to count data movements
        for func_node in functions:
            # Initialize data movement counters for the four COSMIC movement types
            movements = {'E': 0, 'X': 0, 'R': 0, 'W': 0}
            
            # Walk every AST node within this function to classify data movements
            for node in ast.walk(func_node):
                # Analyze function/method calls to detect data movement patterns
                if isinstance(node, ast.Call):
                    func_name = ''   # Will store the simple function/method name
                    full_call = ''   # Will store the full dotted call chain (e.g., "db.query")
                    
                    # Direct function call: e.g., print(...), input(...)
                    if isinstance(node.func, ast.Name):
                        func_name = node.func.id.lower()
                    # Attribute-based method call: e.g., obj.method(...)
                    elif isinstance(node.func, ast.Attribute):
                        func_name = node.func.attr.lower()
                        # Try to reconstruct the full call chain for more precise pattern matching
                        if isinstance(node.func.value, ast.Name):
                            # Simple attribute access: e.g., db.query -> "db.query"
                            full_call = f"{node.func.value.id}.{func_name}".lower()
                        elif isinstance(node.func.value, ast.Attribute):
                            # Chained attribute: e.g., self.db.query -> "*.query"
                            full_call = f"*.{func_name}".lower()
                    
                    # Only proceed if we successfully extracted a function name
                    if func_name:
                        # --- Detect persistent storage READ (R movement) ---
                        # Check if the function name matches known database read patterns
                        if any(pattern in func_name for pattern in db_read_patterns):
                            # Verify against specific database query keywords in the full call
                            if any(keyword in full_call for keyword in {'query', 'select', 'find', 'filter'}):
                                movements['R'] += 1  # Count as a Read data movement
                                continue  # Skip to next node (each call counts as one movement)
                        
                        # TODO: maybe separate to sub function for clarity
                        
                        # Check for file read operations
                        if func_name in file_read_patterns or 'read' in func_name:
                            movements['R'] += 1  # Count as a Read data movement
                            continue
                        
                        # --- Detect persistent storage WRITE (W movement) ---
                        # Check if the function name matches known database write patterns
                        if any(pattern in func_name for pattern in db_write_patterns):
                            movements['W'] += 1  # Count as a Write data movement
                            continue
                        
                        # Check for file write operations
                        if func_name in file_write_patterns or 'dump' in func_name:
                            movements['W'] += 1  # Count as a Write data movement
                            continue
                        
                        # --- Detect user/external INPUT (E movement - Entry) ---
                        if any(pattern in func_name for pattern in entry_patterns):
                            movements['E'] += 1  # Count as an Entry data movement
                            continue
                        
                        # --- Detect user/external OUTPUT (X movement - Exit) ---
                        if any(pattern in func_name for pattern in exit_patterns):
                            # Exclude 'return' here; return statements are handled separately below
                            if func_name != 'return':
                                movements['X'] += 1  # Count as an Exit data movement
                                continue
                
                # Count explicit return statements with a value as Exit movements
                # A function returning a value is outputting data to its caller
                if isinstance(node, ast.Return) and node.value is not None:
                    movements['X'] += 1
                
                # Count yield/yield-from as Exit movements (generator output)
                if isinstance(node, (ast.Yield, ast.YieldFrom)):
                    movements['X'] += 1
            
            # Sum all data movements (E + X + R + W) to get the CFP for this functional process.
            # Per COSMIC: minimum process size is 2 CFP, but we sum raw movements here.
            process_size = sum(movements.values())
            # Add this function's CFP to the total
            total_cfp += process_size
        
        # Ensure at least 1 CFP to prevent division-by-zero in SCI calculation
        return max(total_cfp, 1)
        
    except Exception as e:
        # If analysis fails (syntax errors, encoding issues), warn and return minimum CFP
        print(f"⚠️  Warning: Could not calculate COSMIC CFP for {file_path}: {e}")
        return 1

# TODO: Decide what metrics to use? SCI per LOC? SCI per CFP? SCI per LOC code smells? Carbon reduction per LOC of code smells reduced?
def calculate_green_metrics(
    energy_consumed_kwh,
    emissions_rate_grams_per_kwh,
    total_lines_of_code,
    embodied_carbon=0 # Because we use the same environment so no need to calculate for compare the result
):
    """
    Calculate comprehensive green metrics for code analysis
    
    SCI Formula: SCI = ((E × I) + M) / R
    
    Where:
    - E = Energy consumed (kWh)
    - I = Carbon intensity (gCO2eq/kWh)
    - M = Embodied carbon (gCO2eq)
    - R = Lines of Code (LOC) - the functional unit
    
    Returns dict with SCI metrics
    """
    
    # Calculate total operational carbon emissions: energy (kWh) × carbon intensity (gCO2eq/kWh)
    operational_emissions = energy_consumed_kwh * emissions_rate_grams_per_kwh
    # Total emissions = operational + embodied (embodied is 0 since we reuse the same environment)
    total_emissions = operational_emissions + embodied_carbon
    
    # Metric 1: SCI per LOC - carbon emissions divided by lines of code smells
    if total_lines_of_code > 0:
        # SCI formula: ((E × I) + M) / R where R = LOC
        sci_per_line = total_emissions / total_lines_of_code
    else:
        # Avoid division by zero when no code smell lines exist
        sci_per_line = 0
    
    # Return a dictionary containing the computed green metrics
    return {
        "total_emissions_gCO2eq": total_emissions,       # Total carbon emissions in grams CO2 equivalent
        "total_loc_code_smells": total_lines_of_code,     # Total lines of code with smells
        "sci_gCO2eq_per_line": sci_per_line,              # SCI score: grams CO2eq per line of code
    }

def determine_green_status(current_sci_per_exec, previous_sci_per_exec):
    """
    Compare current SCI per LOC with previous run to determine improvement status.
    Uses a 10% threshold band to classify as improved, degraded, or stable.
    
    Args:
        current_sci_per_exec: Current SCI value (gCO2eq per line of code).
        previous_sci_per_exec: Previous SCI value for comparison, or None for first run.
    
    Returns:
        A status string: 'Initial', 'Greener ✅', 'Hotter ⚠️', or 'Normal'.
    """
    # If no previous value exists, this is the first run
    if previous_sci_per_exec is None:
        return "Initial"
    # If current SCI is more than 10% lower than previous, it's an improvement
    elif current_sci_per_exec < previous_sci_per_exec * 0.90:  # 10% improvement threshold
        return "Greener ✅"
    # If current SCI is more than 10% higher than previous, it's a degradation
    elif current_sci_per_exec > previous_sci_per_exec * 1.10:  # 10% increase threshold
        return "Hotter ⚠️"
    # Otherwise, within the ±10% band - considered stable
    else:
        return "Normal"

# TODO: Can we separate sub-function for clarity?
def impact_analysis(data, avg_emission, total_loc):
    """
    Display code smell LOC vs carbon emission analysis comparing previous and current runs.
    
    Args:
        data: List of historical metric entries
        avg_emission: Current average carbon emission (kg CO2)
        total_loc: Current total lines of code smells
    """
    # Print section header for the impact analysis
    print(f"\n📊 Code Smell LOC vs Carbon Emission Analysis")
    # Need at least 2 data points (previous + current) for comparison
    if len(data) >= 2:
        # Retrieve previous run's emission and LOC values for comparison
        previous_emission = data[-2].get("emission_kg")
        previous_loc = data[-2].get("lines_of_code", 0)
        # Use the current total LOC, defaulting to 0 if None
        current_loc = total_loc if total_loc else 0
        
        # Calculate the differences between previous and current values
        carbon_diff = previous_emission - avg_emission  # Positive = decreased emissions (good)
        loc_diff = previous_loc - current_loc            # Positive = fewer code smell LOC (good)
        
        # Display the previous run's metrics
        print(f"\n   Previous Run:")
        print(f"      Carbon Emission: {previous_emission:.6e} kg CO2")
        print(f"      Code Smell LOC:  {previous_loc} LOC")
        # Show carbon-per-LOC ratio if LOC is non-zero
        if previous_loc > 0:
            print(f"      Carbon per LOC:  {previous_emission / previous_loc:.6e} kg CO2/LOC")
        
        # Display the current run's metrics
        print(f"\n   Current Run:")
        print(f"      Carbon Emission: {avg_emission:.6e} kg CO2")
        print(f"      Code Smell LOC:  {current_loc} LOC")
        # Show carbon-per-LOC ratio or congratulate if all smells are fixed
        if current_loc > 0:
            print(f"      Carbon per LOC:  {avg_emission / current_loc:.6e} kg CO2/LOC")
        else:
            print(f"      ✅ All code smells fixed! (0 LOC)")
        
        # Display the impact comparison between previous and current runs
        print(f"\n   Impact Analysis:")
        
        # Determine LOC change status message
        if loc_diff > 0:
            # Positive diff means fewer code smell lines than before (improvement)
            loc_status = f"✅ Code smells reduced by {loc_diff} LOC"
        elif loc_diff < 0:
            # Negative diff means more code smell lines than before (regression)
            loc_status = f"⚠️  Code smells increased by {abs(loc_diff)} LOC"
        else:
            # No change in LOC
            loc_status = f"➡️  Code smell LOC unchanged ({current_loc} LOC)"
        
        # Determine carbon emission change status message
        if carbon_diff > 0:
            # Positive diff means lower emissions than before (improvement)
            carbon_status = f"✅ Carbon emission decreased by {carbon_diff:.6e} kg CO2"
        elif carbon_diff < 0:
            # Negative diff means higher emissions than before (regression)
            carbon_status = f"⚠️  Carbon emission increased by {abs(carbon_diff):.6e} kg CO2"
        else:
            # No change in emissions
            carbon_status = f"➡️  Carbon emission unchanged"
        
        # Print the LOC and carbon status messages
        print(f"      {loc_status}")
        print(f"      {carbon_status}")
        
        # Show correlation between LOC changes and carbon changes
        if loc_diff != 0 and carbon_diff != 0:
            # Both LOC and carbon changed - analyze correlation direction
            if (loc_diff > 0 and carbon_diff > 0) or (loc_diff < 0 and carbon_diff < 0):
                # Positive correlation: LOC and carbon moved in the same direction
                # This means reducing code smells reduces carbon emissions (or vice versa)
                metric = abs(carbon_diff) / abs(loc_diff)  # Carbon saved per LOC change
                if loc_diff > 0:
                    # LOC decreased and carbon decreased - beneficial correlation
                    print(f"      📉 Carbon saved per LOC removed: {metric:.6e} kg CO2/LOC")
                    print(f"      💡 Less code smell = Less carbon emission!")
                else:
                    # LOC increased and carbon increased - warning correlation
                    print(f"      📈 Carbon increase per LOC added: {metric:.6e} kg CO2/LOC")
                    print(f"      💡 More code smell = More carbon emission")
            else:
                # Negative correlation - LOC and carbon moved in opposite directions
                # Other factors (hardware, background processes) may be involved
                print(f"      ℹ️  Carbon change may be due to other factors")
        elif loc_diff == 0 and carbon_diff != 0:
            # LOC didn't change but carbon did - other optimizations at play
            print(f"      ℹ️  Carbon change from other optimizations/factors")
    else:
        # First run - no comparison data available yet
        print(f"\n   Current Run (Initial):")
        print(f"      Carbon Emission: {avg_emission:.6e} kg CO2")
        print(f"      Code Smell LOC:  {total_loc if total_loc else 0} LOC")
        # Show carbon-per-LOC if total_loc is non-zero
        if total_loc and total_loc > 0:
            print(f"      Carbon per LOC:  {avg_emission / total_loc:.6e} kg CO2/LOC")
        print(f"      ℹ️  No previous run to compare")

def get_python_files(path):
    """
    Collect all Python (.py) files from the given path.
    
    If path is a single file, validates it's a .py file and returns it in a list.
    If path is a directory, recursively finds all .py files while excluding
    common non-source directories (venv, __pycache__, .git, node_modules, etc.).
    
    Args:
        path: A file path or directory path (string or Path).
    
    Returns:
        A sorted list of Path objects pointing to Python files.
    """
    # Convert the input path to a Path object for consistent handling
    path = Path(path)
    
    # Handle single-file input
    if path.is_file():
        # Validate that the file is a Python (.py) file
        if path.suffix == '.py':
            return [path]  # Return as a single-element list for uniform processing
        else:
            # Reject non-Python files with an error and exit
            print(f"❌ Error: '{path}' is not a Python file!")
            sys.exit(1)
    # Handle directory input
    elif path.is_dir():
        # Directories to exclude from recursive search (virtual envs, caches, etc.)
        exclude_dirs = {'venv', '.venv', 'env', '__pycache__', '.git', 'node_modules', '.pytest_cache', '.tox'}
        # Accumulator for discovered Python files
        python_files = []
        
        # Recursively search for all .py files in the directory tree
        for py_file in path.rglob('*.py'):
            # Skip files located inside any excluded directory
            if not any(parent.name in exclude_dirs for parent in py_file.parents):
                python_files.append(py_file)
        
        # Return the list sorted alphabetically for deterministic analysis order
        return sorted(python_files)
    else:
        # Path doesn't exist - error and exit
        print(f"❌ Error: Path '{path}' not found!")
        sys.exit(1)

def find_main_file(path):
    """
    Attempt to automatically detect the main entry point file in a project.
    
    Searches for files containing `if __name__ == "__main__":` blocks.
    If multiple candidates are found, returns an error message asking the user
    to specify. Also detects files with `def main()` but no entry point guard.
    
    Args:
        path: A file path or directory path to search.
    
    Returns:
        - A Path to the detected entry point file, or
        - An error message string (prefixed with 'error'), or
        - None if no entry point is found.
    """
    # Convert input to a Path object for consistent handling
    path = Path(path)
    
    # --- Single file mode ---
    if path.is_file():
        # Check for a proper entry point guard: if __name__ == "__main__":
        if has_main_entry(path):
            return path  # File has a valid main entry point
        # Check for def main() without the entry point guard
        if has_main_function_only(path):
            return f"error has main function only {path}"  # Return error string
        return None  # No entry point found in this file
    
    # --- Directory mode: search all Python files for entry points ---
    if path.is_dir():
        # Accumulators for files with entry points vs. files with only def main()
        candidates = []            # Files with if __name__ == "__main__":
        main_only_candidates = []  # Files with def main() but no guard
        
        # Recursively search all Python files in the project directory
        for py_file in path.rglob('*.py'):
            # Skip files inside excluded directories (venv, __pycache__, etc.)
            exclude_dirs = {'venv', '.venv', 'env', '__pycache__', '.git', 'node_modules', '.pytest_cache', '.tox'}
            if any(parent.name in exclude_dirs for parent in py_file.parents):
                continue  # Skip this file and move to the next one
            
            # Classify each file by its entry point type
            if has_main_entry(py_file):
                candidates.append(py_file)           # Has proper entry point
            elif has_main_function_only(py_file):
                main_only_candidates.append(py_file)  # Has def main() but no guard
        
        # --- Handle the case: no entry points found, but def main() exists ---
        if len(candidates) == 0 and len(main_only_candidates) > 0:
            if len(main_only_candidates) == 1:
                # Single file has def main() without guard
                return f"error has main function only {main_only_candidates[0]}"
            else:
                # Multiple files have def main() without guard
                return f"error has main function only multiple {' '.join(str(f) for f in main_only_candidates)}"
        
        # No entry points and no main functions found at all
        if len(candidates) == 0:
            return "error no entry point found"
        
        # Multiple entry points found - user must specify which one to run
        if len(candidates) > 1:
            print(f"🔍 Found {len(candidates)} main entry candidates:")
            for candidate in candidates:
                # Display relative paths for readability when possible
                try:
                    display_path = candidate.relative_to(Path.cwd())
                except ValueError:
                    display_path = candidate
                print(f"    {display_path}")
            print()
            return "error too many entry point found please specify"
        
        # Exactly one entry point found - return it
        if candidates:
            return candidates[0]
    
    # Path is neither file nor directory
    return None

def has_main_entry(file_path):
    """
    Check if a Python file has a proper main entry point.
    
    Parses the file's AST to look for the idiomatic guard:
        if __name__ == "__main__":
    
    Args:
        file_path: Path to the Python file to inspect.
    
    Returns:
        True if the file contains a __name__ == '__main__' check, False otherwise.
    """
    try:
        # Read the Python file content with UTF-8 encoding
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse the source code into an AST for structural analysis
        tree = ast.parse(content)
        
        # Walk every node in the AST looking for the entry point guard pattern
        for node in ast.walk(tree):
            # Look for 'if' statements at the module level
            if isinstance(node, ast.If):
                # Check if the condition is a comparison expression
                if isinstance(node.test, ast.Compare):
                    # Verify the left side is the name '__name__'
                    if isinstance(node.test.left, ast.Name) and node.test.left.id == '__name__':
                        # Verify the right side compares against the string "__main__"
                        if any(isinstance(comp, ast.Constant) and comp.value == "__main__" 
                               for comp in node.test.comparators):
                            return True  # Found: if __name__ == "__main__":
        
        return False  # No entry point guard found in the entire AST
    except:
        return False  # Return False on any parsing/reading errors

def has_main_function_only(file_path):
    """
    Check if a Python file defines a `main()` function but lacks a proper entry point.
    
    This indicates the developer likely intended the file to be runnable but forgot
    to add the `if __name__ == "__main__":` guard.
    
    Args:
        file_path: Path to the Python file to inspect.
    
    Returns:
        True if the file has `def main()` but no `if __name__ == '__main__':` block.
    """
    try:
        # Read the Python file content with UTF-8 encoding
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse the source code into an AST for structural analysis
        tree = ast.parse(content)
        
        # Track whether we find each pattern independently
        has_name_main = False   # Flag for if __name__ == "__main__"
        has_main_func = False   # Flag for def main()
        
        # Walk every node in the AST to check for both patterns
        for node in ast.walk(tree):
            # Check for if __name__ == "__main__": guard
            if isinstance(node, ast.If):
                if isinstance(node.test, ast.Compare):
                    # Verify the left side is '__name__'
                    if isinstance(node.test.left, ast.Name) and node.test.left.id == '__name__':
                        # Verify the right side compares against "__main__"
                        if any(isinstance(comp, ast.Constant) and comp.value == "__main__" 
                               for comp in node.test.comparators):
                            has_name_main = True  # Entry point guard found
            
            # Check for def main(): function definition
            if isinstance(node, ast.FunctionDef) and node.name == 'main':
                has_main_func = True  # main() function found
        
        # Return True only if main() exists but the entry point guard is missing
        return has_main_func and not has_name_main
    except:
        return False  # Return False on any parsing/reading errors

def setup_rules(args):
    """
    Instantiate and configure analysis rules based on CLI arguments.
    
    Creates rule objects (GodClass, DuplicatedCode, LongMethod, DeadCode,
    MutableDefaultArguments) unless the user has disabled them via --no-* flags.
    Rule thresholds are sourced from the parsed args.
    
    Args:
        args: Parsed argparse namespace containing rule configuration flags and thresholds.
    
    Returns:
        A list of instantiated rule objects ready for analysis.
    """
    # Accumulator for enabled rule instances
    rules = []
    
    # Instantiate GodClassRule unless disabled via --no-god-class flag
    if not args.no_god_class:
        rules.append(GodClassRule(
            max_methods=args.max_methods,   # Maximum number of methods before triggering (default: 10)
            max_cc=args.max_cc,             # Maximum cyclomatic complexity threshold (default: 35)
            max_loc=args.max_loc            # Maximum lines of code threshold (default: 100)
        ))
    
    # Instantiate DuplicatedCodeRule unless disabled via --no-dup-check flag
    if not args.no_dup_check:
        rules.append(DuplicatedCodeRule(
            similarity_threshold=args.dup_similarity,          # Code similarity threshold (default: 0.85)
            min_statements=args.dup_min_statements,            # Minimum statements to consider (default: 3)
            check_within_functions=args.dup_check_within,      # Check for duplication within functions
            check_between_functions=args.dup_check_between     # Check for duplication between functions
        ))
    
    # Instantiate LongMethodRule unless disabled via --no-long-method flag
    if not args.no_long_method:
        rules.append(LongMethodRule(
            max_loc=args.method_max_loc,    # Maximum lines per method (default: 25)
            max_cc=args.max_cyclomatic      # Maximum cyclomatic complexity per method (default: 10)
        ))
    
    # Instantiate DeadCodeRule unless disabled via --no-dead-code flag
    if not args.no_dead_code:
        rules.append(DeadCodeRule())  # No configurable thresholds for dead code detection

    # Instantiate MutableDefaultArgumentsRule unless disabled via --no-mutable-default flag
    if not args.no_mutable_default:
        rules.append(MutableDefaultArgumentsRule())  # No configurable thresholds

    # If no rules are enabled, warn and exit since there's nothing to analyze
    if not rules:
        print("⚠️  Warning: No rules enabled!")
        sys.exit(0)
    
    # Return the list of instantiated rule objects
    return rules

def count_total_loc_code_smells(all_results):
    """
    Sum the total lines of code affected by code smells across all analysis results.
    
    For each issue, calculates the span (end_lineno - lineno + 1). MutableDefaultArguments
    issues are counted as 1 line each since they are single-line issues.
    
    Args:
        all_results: A dict mapping file paths to lists of issue dictionaries.
    
    Returns:
        The total number of lines of code involved in code smells (int).
    """
    # Initialize the running total of code smell LOC
    total_loc = 0
    
    # Iterate over each file's list of issues in the results dictionary
    for issues in all_results.values():
        # Process each individual issue found in the file
        for issue in issues:
            # MutableDefaultArguments issues are always single-line, so count as 1
            if issue.get('rule') == 'MututableDefaultArguments':
                total_loc += 1
                continue  # Skip the line-range calculation for this single-line issue
            # Get the start and end line numbers for this issue
            lineno = issue.get('lineno')
            end_lineno = issue.get('end_lineno', lineno)  # Default to same line if no end_lineno
            # Calculate the number of lines spanned by this issue
            if lineno and end_lineno:
                total_loc += (end_lineno - lineno + 1)  # Inclusive range: end - start + 1
            # print(f"Debug: Issue {issue.get('rule')} loc of code smells: {end_lineno - lineno + 1}")
    
    # Return the total lines of code affected by all code smells
    return total_loc

def analyze_code_smells(path, args):
    """
    Run code smell analysis on the given path (file or directory).
    
    Discovers Python files, sets up rules from args, and delegates to
    analyze_file() or analyze_project() depending on whether the path is a
    file or directory. Also displays formatted results to the console.
    
    Args:
        path: Path to a Python file or project directory.
        args: Parsed argparse namespace with rule configuration.
    
    Returns:
        A tuple of (all_results, total_loc) where all_results is a dict mapping
        file Paths to issue lists, and total_loc is the total lines affected.
    """
    # Discover all Python files at the given path (file or directory)
    python_files = get_python_files(path)
    
    # Exit early if no Python files found in the specified path
    if not python_files:
        print(f"⚠️  No Python files found in '{path}'")
        sys.exit(0)
    
    # Display the number of files to be analyzed
    print(f"🔍 Analyzing {len(python_files)} Python file(s)...\n")
    
    # Instantiate and configure all analysis rules based on CLI arguments
    rules = setup_rules(args)
    
    # Choose analysis mode based on whether path is a directory or single file
    if Path(path).is_dir():
        # Project mode: use analyze_project() which handles cross-file rules (e.g., DeadCodeRule)
        all_issues = analyze_project(path, rules)
        # Group the flat list of issues by file path into a dictionary
        all_results = {}
        for issue in all_issues:
            file_path = issue.get('file')  # Each issue has a 'file' key from analyze_project
            if file_path:
                file_key = Path(file_path)
                # Initialize the list for this file if it's the first issue
                if file_key not in all_results:
                    all_results[file_key] = []
                all_results[file_key].append(issue)
        # Count total issues across all files
        total_issues = len(all_issues)
    else:
        # Single-file mode: analyze just the one file
        all_results = {}
        all_issues = analyze_file(str(python_files[0]), rules, project_root=path)
        # Store results if any issues were found
        if all_issues:
            all_results[python_files[0]] = all_issues
        total_issues = len(all_issues)

    # Calculate the total lines of code affected by code smells
    total_loc = count_total_loc_code_smells(all_results)
    
    # Display formatted results to the console
    display_results(all_results, total_issues, python_files, args)
    
    # Return both the results dictionary and total LOC for downstream use (carbon tracking)
    return all_results, total_loc

def display_results(all_results, total_issues, all_files, args):
    """
    Display code smell analysis results to the console in a formatted layout.
    
    Shows issues grouped by file and then by rule type, with a summary count
    per rule at the end. Files are sorted by number of issues (descending).
    
    Args:
        all_results: Dict mapping file paths to lists of issue dictionaries.
        total_issues: Total number of issues found across all files.
        all_files: List of all Python files that were analyzed.
        args: Parsed argparse namespace (reserved for future display options).
    """
    # If no issues were found across all files, display a success message
    if not all_results:
        print(f"✅ No issues found in {len(all_files)} file(s)!")
        return
    
    # Print the header with total issue count
    print("=" * BREAK_LINE_NO)
    print(f"⚠️  Found {total_issues} issue(s) in {len(all_results)} file(s):")
    print("=" * BREAK_LINE_NO)
    
    # Sort files by number of issues (most issues first) for prioritized display
    sorted_files = sorted(all_results.items(), key=lambda x: len(x[1]), reverse=True)
    
    # Display issues for each file
    for file_path, issues in sorted_files:
        # Try to display a relative path for readability
        try:
            display_path = file_path.relative_to(Path.cwd())
        except (ValueError, TypeError):
            # Handle case where file_path is a string (convert to Path first)
            try:
                display_path = Path(file_path).relative_to(Path.cwd())
            except ValueError:
                display_path = Path(file_path)  # Fall back to absolute path
        
        # Print the file header with the file path and issue count
        print(f"\n📄 {display_path} ({len(issues)} issue(s))")
        print("-" * BREAK_LINE_NO)
        
        # Group issues by their rule name for organized display
        by_rule = {}
        for issue in issues:
            rule = issue['rule']  # Get the rule name (e.g., "GodClass", "LongMethod")
            if rule not in by_rule:
                by_rule[rule] = []  # Initialize list for this rule if first occurrence
            by_rule[rule].append(issue)
        
        # Display each rule group with its issues, sorted alphabetically by rule name
        for rule_name, rule_issues in sorted(by_rule.items()):
            print(f"\n  {rule_name} ({len(rule_issues)} issue(s)):")
            # Print each issue's line number and message
            for issue in rule_issues:
                print(f"    Line {issue['lineno']}: {issue['message']}")

    # Print a summary section showing total counts per rule type
    print("\n" + "=" * BREAK_LINE_NO)
    print("📊 Summary by Rule:")
    print("-" * BREAK_LINE_NO)
    
    # Aggregate issue counts across all files by rule name
    rule_summary = {}
    for issues in all_results.values():
        for issue in issues:
            rule = issue['rule']
            rule_summary[rule] = rule_summary.get(rule, 0) + 1  # Increment count for this rule
    
    # Display the summary sorted by count (most frequent first)
    for rule_name, count in sorted(rule_summary.items(), key=lambda x: x[1], reverse=True):
        print(f"  {rule_name}: {count} issue(s)")
    
    # Print closing separator
    print("=" * BREAK_LINE_NO + "\n")

def carbon_track(path, args, total_loc=0):
    """
    Track carbon emissions by running the target Python application 5 times.
    
    Uses CodeCarbon's EmissionsTracker to measure energy consumption and CO2
    emissions for each run. Computes averages, calculates SCI metrics (per LOC
    and per COSMIC Function Point), compares with historical data from
    history.json, and prints a detailed carbon emissions report.
    
    Args:
        path: Path to the file or project being analyzed.
        args: Parsed argparse namespace; uses args.carbon_run and args.no_carbon.
        total_loc: Total lines of code affected by code smells (for SCI per LOC).
    
    Returns:
        A metric dictionary with emission data and SCI scores, or None on failure.
    """
    # Skip carbon tracking if CodeCarbon is not installed or user disabled it
    if not CODECARBON_AVAILABLE or args.no_carbon:
        return
    
    # --- Determine which Python file to execute for carbon measurement ---
    target_file = None
    
    if args.carbon_run:
        # User explicitly specified a file to run via --carbon-run flag
        target_file = Path(args.carbon_run)
        # Validate that the specified file exists
        if not target_file.exists():
            print(f"⚠️  Warning: Specified file '{args.carbon_run}' not found. Skipping carbon tracking.")
            return
        # Validate that the specified file is a Python file
        if not target_file.suffix == '.py':
            print(f"⚠️  Warning: Specified file '{args.carbon_run}' is not a Python file. Skipping carbon tracking.")
            return
    else:
        # No file specified - try to auto-detect the main entry point
        target_file = find_main_file(path)
        
        # Handle error messages returned from find_main_file as strings
        if isinstance(target_file, str):
            if target_file.startswith("error has main function only"):
                # File(s) have def main() but lack the if __name__ == "__main__": guard
                if target_file.startswith("error has main function only multiple"):
                    # Multiple files have def main() without entry point guard
                    files_part = target_file.replace("error has main function only multiple ", "")
                    print("⚠️  Found files with def main() but no entry point:")
                    for f in files_part.split():
                        print(f"    {f}")
                    print("   Files must contain: if __name__ == \"__main__\":")
                else:
                    # Single file has def main() without entry point guard
                    file_path = target_file.replace("error has main function only ", "")
                    print(f"⚠️  Warning: {file_path} has def main() but no entry point.")
                    print("   The file must contain: if __name__ == \"__main__\":")
                # Suggest alternative options to the user
                print("   Use --carbon-run <file.py> to specify a file with proper entry point, or")
                print("   use --no-carbon to disable carbon tracking.\n")
            elif target_file == "error no entry point found":
                # No files with entry points found anywhere in the project
                print("⚠️  No main entry point found for carbon tracking.")
                print("   Use --carbon-run <file.py> to specify the file to run, or")
                print("   use --no-carbon to disable carbon tracking.\n")
            elif target_file == "error too many entry point found please specify":
                # Multiple valid entry points found - user must disambiguate
                print("⚠️  Multiple main entry point candidates found. Please specify which one to run.")
                print("   Use --carbon-run <file.py> to specify the file to run, or")
                print("   use --no-carbon to disable carbon tracking.\n")
            return  # Stop carbon tracking on any find_main_file error
        
        # No main entry point found at all (find_main_file returned None)
        if not target_file:
            print("⚠️  No main entry point found for carbon tracking.")
            print("   Use --carbon-run <file.py> to specify the file to run, or")
            print("   use --no-carbon to disable carbon tracking.\n")
            return
    
    # Display which file will be run and the iteration plan
    print(f"\n🌱 Tracking carbon emissions for: {target_file}")
    print("   Running 5 iterations for average calculations...")
    print("-" * BREAK_LINE_NO)
    
    # Run the target file 5 times with CodeCarbon tracking, collecting emission data
    # TODO: Extract to new method like run_entry_point(target_file)? 5 times 
    # then use function find_avg_code_carbon_data(all_runs)?
    all_runs = []  # Accumulator for successful run data dictionaries
    
    try:
        # Suppress CodeCarbon's verbose logging to keep output clean
        import logging
        logging.getLogger("codecarbon").setLevel(logging.CRITICAL)
        
        # Execute the target file 5 times to get stable average measurements
        for run_num in range(1, 6):
            print(f"\n▶️  Run {run_num}/5...")
            tracker = None          # Will hold the EmissionsTracker instance
            emissions_data = None   # Will hold the final emissions data after stopping
            
            try:
                # Initialize a new EmissionsTracker for this run
                tracker = EmissionsTracker(
                    log_level="critical",           # Suppress internal logging
                    save_to_file=False,             # Don't write emissions.csv
                    save_to_api=False,              # Don't send data to CodeCarbon API
                    allow_multiple_runs=True,        # Allow multiple tracker instances
                    project_name=f"carbon_track_{target_file.stem}"  # Name based on target file
                )
                # Start measuring energy consumption and emissions
                tracker.start()
                
                # Run the target Python file as a subprocess using the current Python interpreter
                result = subprocess.run(
                    [sys.executable, str(target_file)],  # Command: python <target_file>
                    capture_output=True,                  # Capture stdout and stderr
                    text=True,                            # Decode output as text (not bytes)
                    timeout=30                            # Kill subprocess after 30 seconds
                )
                
                # Stop the emissions tracker and get the total duration
                duration = tracker.stop()
                # Retrieve the final emissions data object from the tracker
                emissions_data = tracker.final_emissions_data
                
                # If emissions data was successfully collected, store it
                if emissions_data:
                    all_runs.append({
                        'duration': duration,                        # Total tracking duration in seconds
                        'emission': emissions_data.emissions,        # CO2 emissions in kg
                        'energy_consumed': emissions_data.energy_consumed,  # Energy in kWh
                        'cpu_power': emissions_data.cpu_power,       # CPU power draw in watts
                        'ram_power': emissions_data.ram_power,       # RAM power draw in watts
                        'cpu_energy': emissions_data.cpu_energy,     # CPU energy in kWh
                        'ram_energy': emissions_data.ram_energy,     # RAM energy in kWh
                        'emissions_rate': emissions_data.emissions_rate,  # kg CO2/kWs rate
                        'region': emissions_data.region,             # Geographic region
                        'country_name': emissions_data.country_name, # Country name
                    })
                    print(f"  ✓ Run {run_num} completed")
            
            except subprocess.TimeoutExpired:
                # The subprocess exceeded the 30-second timeout
                print(f"  ⚠️  Run {run_num} timed out")
                continue  # Skip this run and try the next one
            except Exception as e:
                # Any other error during this run (e.g., tracker initialization failure)
                print(f"  ⚠️  Run {run_num} failed: {e}")
                continue  # Skip this run and try the next one
        
        # Display the program's stdout output from the last run
        if result.stdout:
            print("\n📋 Program output (from first run):")
            print(result.stdout)
        else:
            print("\n⚠️  No output captured. The entry point was executed but may not have produced any output.")
        
        # Display any stderr output (warnings, errors) from the last run
        if result.stderr:
            print("\n⚠️  Program errors/warnings:")
            print(result.stderr)
        
        # Warn if the program exited with a non-zero exit code
        if result.returncode != 0:
            print(f"\n⚠️  Program exited with code {result.returncode}")

    except Exception as e:
        # Handle any unexpected errors during the entire carbon tracking process
        print(f"⚠️  Error during carbon tracking: {e}")
        return
    
    # TODO: Extract to new method like find_avg_code_carbon_data(all_runs)?
    # Process results only if at least one run succeeded
    if all_runs:
        # Calculate average values across all successful runs for stable measurements
        # avg_duration = sum(r['duration'] for r in all_runs) / len(all_runs)
        avg_emission = sum(r['emission'] for r in all_runs) / len(all_runs)       # Average CO2 emissions (kg)
        avg_energy = sum(r['energy_consumed'] for r in all_runs) / len(all_runs)   # Average energy consumed (kWh)
        # avg_cpu_power = sum(r['cpu_power'] for r in all_runs) / len(all_runs)
        # avg_ram_power = sum(r['ram_power'] for r in all_runs) / len(all_runs)
        # avg_cpu_energy = sum(r['cpu_energy'] for r in all_runs) / len(all_runs)
        # avg_ram_energy = sum(r['ram_energy'] for r in all_runs) / len(all_runs)
        avg_emissions_rate = sum(r['emissions_rate'] for r in all_runs) / len(all_runs)  # Average rate (kg CO2/kWs)
        # Use the geographic info from the first run (should be the same for all runs)
        region = all_runs[0]['region']
        country_name = all_runs[0]['country_name']

        # Convert emissions rate from CodeCarbon's native kg CO2/kWs to gCO2eq/kWh.
        # Multiply by SEC_HOUR (3600) to convert seconds to hours and KG_GRAMS (1000) for kg to grams.
        emissions_rate_grams = avg_emissions_rate * SEC_HOUR * KG_GRAMS
        
        # Calculate green metrics (SCI per LOC) using the SCI formula: ((E × I) + M) / R
        green_metrics = calculate_green_metrics(
            energy_consumed_kwh=avg_energy,            # E: energy consumed
            emissions_rate_grams_per_kwh=emissions_rate_grams,  # I: carbon intensity
            total_lines_of_code=total_loc,              # R: functional unit (LOC of code smells)
            embodied_carbon=0                           # M: embodied carbon (0 for same environment)
        )

        # Calculate COSMIC Function Points (CFP) from the target file for SCI per CFP metric
        cosmic_cfp = calculate_cosmic_cfp(target_file)
        
        # Calculate SCI per COSMIC Function Point:
        # Formula: (E_kWh × I_kg_CO2_per_kWh × 1000_g_per_kg) / R_CFP
        # Result is in gCO2eq per function point
        if cosmic_cfp > 0:
            sci_per_cfp = (avg_energy * avg_emissions_rate * 1000) / cosmic_cfp
        else:
            sci_per_cfp = 0  # Avoid division by zero

        # TODO: Extract to new method like save_metric_as_history()?
        # --- Load historical run data from history.json for comparison ---
        file_path = "history.json"  # Path to the history file storing previous run metrics
        if os.path.exists(file_path):
            # Read existing history data
            with open(file_path, "r") as f:
                try:
                    data = json.load(f)  # Parse JSON content
                    # Ensure data is always a list (handle single-object legacy format)
                    if not isinstance(data, list):
                        data = [data]
                except json.JSONDecodeError:
                    data = []  # Reset to empty list on corrupt JSON
        else:
            data = []  # No history file exists yet

        # --- Determine the run status by comparing with the previous run ---
        if len(data) == 0:
            # First run ever - no comparison baseline available
            status = "Initial"
            id_num = 1  # Start ID numbering at 1
            previous_sci_per_loc = None  # No previous SCI value
        else:
            # Subsequent run - compare with the most recent historical entry
            id_num = data[-1]["id"] + 1  # Increment ID from the last entry
            previous_sci_per_loc = data[-1].get("sci_gCO2eq_per_line")  # Previous SCI per LOC
            # Compare current SCI with previous to determine green/hot/normal status
            status = determine_green_status(
                green_metrics["sci_gCO2eq_per_line"],
                previous_sci_per_loc
            )
        
        # Calculate the improvement percentage compared to the previous run
        if previous_sci_per_loc and previous_sci_per_loc > 0:
            # Percentage change: positive = improvement (less carbon), negative = degradation
            improvement = ((previous_sci_per_loc - green_metrics["sci_gCO2eq_per_line"]) 
                          / previous_sci_per_loc) * 100
        else:
            improvement = None  # No comparison available for first run

        # --- Build the metric dictionary capturing all data for this run ---
        metric = {
            "id": id_num,                                                   # Unique run identifier
            "date_time": str(datetime.now()),                               # Timestamp of this run
            "target_file": str(target_file),                                # File that was executed
            "duration_seconds": duration,                                   # Execution duration in seconds
            "emission_kg": avg_emission,                                    # Average CO2 emissions in kg
            "energy_consumed_kWh": avg_energy,                              # Average energy in kWh
            "region": region,                                               # Geographic region for grid intensity
            "country_name": country_name,                                   # Country name for the region
            "emissions_rate_gCO2eq_per_kWh": emissions_rate_grams,          # Carbon intensity rate
            "total_emissions_gCO2eq": green_metrics["total_emissions_gCO2eq"],  # Total emissions in gCO2eq
            "lines_of_code": green_metrics["total_loc_code_smells"],        # Total LOC of code smells
            "sci_gCO2eq_per_line": green_metrics["sci_gCO2eq_per_line"],    # SCI per LOC metric
            "status": status,                                               # Green status (Initial/Greener/Hotter/Normal)
            "cfp": cosmic_cfp,                                              # COSMIC Function Points count
            "sci_per_cfp": sci_per_cfp,                                     # SCI per COSMIC function point
            "improvement_percent": improvement                              # Improvement % from last run (or None)
        }
        
        # --- Save the updated history back to history.json ---
        data.append(metric)  # Add this run's metric to the history array
        json_str = json.dumps(data, indent=4)  # Serialize to pretty-printed JSON
        with open(file_path, "w") as f:
            f.write(json_str)  # Write the updated history to disk
        
        # TODO: Extract to new method like display_carbon_report()?
        # --- Display the formatted Carbon Emissions Report ---
        print("\n" + "=" * BREAK_LINE_NO)
        print("🌍 GREEN CODE CARBON EMISSIONS REPORT 🌍")
        print("=" * BREAK_LINE_NO)
        # Show execution details: which file was run and how long it took
        print(f"\n📋 Execution Details:")
        print(f"  Target file: {target_file}")
        print(f"  Duration: {duration:.2f} seconds")
        # Show energy consumption and carbon emission measurements
        print(f"\n⚡ Energy & Emissions:")
        print(f"  Total energy consumed: {avg_energy:.6f} kWh")
        print(f"  Carbon emissions: {avg_emission:.6e} kg CO2")
        print(f"  Emissions rate: {emissions_rate_grams:.2f} gCO2eq/kWh")
        print(f"  Region: {region}")
        print(f"  Country: {country_name}")
        # Show code analysis metrics
        print(f"\n📊 Code Metrics:")
        print(f"  COSMIC Function Points: {cosmic_cfp} CFP")
        print(f"  Total lines of code: {green_metrics['total_loc_code_smells']} LOC")
        # Show the SCI (Software Carbon Intensity) scores - the key green metrics
        print(f"\n🌱 SCI Metrics (Software Carbon Intensity):")
        print(f"  ├─ Per line of code: {green_metrics['sci_gCO2eq_per_line']:.8f} gCO2eq/LOC")
        print(f"  │  ℹ️  Lower is greener! Shorter code = lower carbon footprint")
        print(f"  ├─ Per cosmic function point: {sci_per_cfp:.8f} gCO2eq/cfp")
        print(f"  │  ℹ️  Lower is greener! less data movement = less carbon footprint")
        print(f"  └─")
        
        # print(f"\n📈 Status: {status}")
        # if improvement is not None:
        #     print(f"   Previous: {previous_sci_per_loc:6e}")
        #     print(f"   Now: {green_metrics["sci_gCO2eq_per_line"]:6e}")
        #     if improvement > 0:
        #         print(f"   Decrease Carbon emission around: {abs(improvement):.2f}%")
        #     else:
        #         print(f"   Increase Carbon emission around: {abs(improvement):.2f}%")

        # Display the impact analysis comparing current vs previous runs
        impact_analysis(data, avg_emission, total_loc)
        
        # Print closing separator for the report
        print("=" * BREAK_LINE_NO)

        return metric  # Return the metric dictionary for use by worker.py or other callers
    
    # No successful runs completed - return None to indicate failure
    return None

def get_argument_parser():
    """
    Create and return the CLI argument parser for pygreensense.
    
    Defines all command-line options including rule toggles, threshold overrides,
    duplicated code detection modes, and carbon tracking configuration.
    
    Returns:
        An argparse.ArgumentParser configured with all supported arguments.
    """
    # Create the argument parser with a description and example epilog
    parser = argparse.ArgumentParser(
        description='Check Python file or project for green code smells.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze single file
  %(prog)s myfile.py
  
  # Analyze entire project
  %(prog)s ./my_project
  %(prog)s .
  
  # With carbon tracking (auto-detect main file)
  %(prog)s . 
  
  # Specify file to run for carbon tracking
  %(prog)s . --carbon-run main.py
  %(prog)s . --carbon-run src/app.py
  
  # With custom options
  %(prog)s ./src --no-log-check
  %(prog)s . --max-methods 5
  
  # Duplicated code detection options
  %(prog)s . --dup-similarity 0.80
  %(prog)s . --dup-min-statements 5
  %(prog)s . --dup-check-within-only    # Check only within functions
  %(prog)s . --dup-check-between-only   # Check only between functions
  
  %(prog)s . --method-max-loc 30 --max-cyclomatic 3
  %(prog)s . --no-carbon  # Disable carbon tracking
        """
    )
    
    # --- Define all CLI arguments ---
    
    # Positional argument: the path to analyze (file or directory)
    parser.add_argument('path', help='Path to Python file or project directory to check')
    
    # --- Excessive log rule toggle ---
    parser.add_argument('--no-log-check', action='store_true', 
                       help='Disable excessive logging detection')
    
    # --- God Class rule configuration ---
    parser.add_argument('--no-god-class', action='store_true', 
                       help='Disable God Class detection')
    parser.add_argument('--max-methods', type=int, default=10, 
                       help='Max methods for God Class (default: 10)')  # Threshold for method count
    parser.add_argument('--max-cc', type=int, default=35, 
                       help='Max cyclomatic complexity for God Class (default: 35)')  # Complexity threshold
    parser.add_argument('--max-loc', type=int, default=100, 
                       help='Max lines of code for God Class (default: 100)')  # LOC threshold
    
    # --- Duplicated Code rule configuration ---
    parser.add_argument('--no-dup-check', action='store_true', 
                       help='Disable duplicated code detection')
    parser.add_argument('--dup-similarity', type=float, default=0.85, 
                       help='Similarity threshold for duplicated code (0.0-1.0, default: 0.85)')  # How similar code must be to flag
    parser.add_argument('--dup-min-statements', type=int, default=3,
                       help='Minimum statements in code block to check for duplication (default: 3)')  # Minimum block size
    parser.add_argument('--dup-check-within-only', action='store_true',
                       help='Check duplicated code only within functions (not between functions)')  # Intra-function only
    parser.add_argument('--dup-check-between-only', action='store_true',
                       help='Check duplicated code only between functions (not within functions)')  # Inter-function only
    
    # --- Long Method rule configuration ---
    parser.add_argument('--no-long-method', action='store_true', 
                       help='Disable Long Method detection')
    parser.add_argument('--method-max-loc', type=int, default=25, 
                       help='Max lines of code for method (default: 25)')  # LOC threshold per method
    parser.add_argument('--max-cyclomatic', type=int, default=10, 
                       help='Max cyclomatic complexity for method (default: 10)')  # Complexity threshold per method
    
    # --- Dead Code rule toggle ---
    parser.add_argument('--no-dead-code', action='store_true', 
                       help='Disable Dead Code detection')
    
    # --- Mutable Default Arguments rule toggle ---
    parser.add_argument('--no-mutable-default', action='store_true',
                       help='Disable Mutable Default Arguments detection')
    
    # --- Carbon tracking configuration ---
    parser.add_argument('--no-carbon', action='store_true', 
                       help='Disable carbon emissions tracking')  # Skip carbon measurement entirely
    parser.add_argument('--carbon-run', type=str, metavar='FILE',
                       help='Specify Python file to run for carbon tracking (e.g., main.py, app.py)')  # Explicit target
    
    # Return the configured parser
    return parser

def main():
    """
    CLI entry point for running pygreensense from the command line.
    
    Parses arguments, validates options, runs code smell analysis,
    performs carbon tracking, and prints the final summary.
    """
    # Create the CLI argument parser with all supported options
    parser = get_argument_parser()
    # Parse command-line arguments into a namespace object
    args = parser.parse_args()
    
    # If no path was provided, display help and exit
    if args.path is None:
        parser.print_help()
        sys.exit(0)
    
    # Shortcut: "run" keyword maps to current directory "."
    if args.path == "run":
        args.path = "."
    
    # Validate mutually exclusive duplicated code check options
    if args.dup_check_within_only and args.dup_check_between_only:
        # Both flags cannot be set simultaneously - they're contradictory
        print("❌ Error: Cannot use both --dup-check-within-only and --dup-check-between-only")
        sys.exit(1)
    
    # Set the check_within and check_between flags based on user's choice
    if args.dup_check_within_only:
        # Only check for duplication within individual functions
        args.dup_check_within = True
        args.dup_check_between = False
    elif args.dup_check_between_only:
        # Only check for duplication between different functions
        args.dup_check_within = False
        args.dup_check_between = True
    else:
        # Default: check both within and between functions
        args.dup_check_within = True
        args.dup_check_between = True
    
    # Run the code smell analysis on the specified path
    all_result, total_loc = analyze_code_smells(args.path, args)
    # Run carbon tracking (measures emissions by executing the target file 5 times)
    carbon_track(args.path, args, total_loc)

    # Print final completion message
    print("\n✨ Analysis complete.\n")

# Entry point guard: only run main() when this script is executed directly
if __name__ == "__main__":
    main()