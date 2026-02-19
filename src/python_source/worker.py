import sys         # System-level operations: path manipulation, exit codes, stdout access
import json        # JSON encoding/decoding for structured communication with the VS Code extension
import traceback   # Format exception tracebacks for error reporting to stderr
import io          # In-memory text streams (StringIO) to capture stdout from sub-libraries
import contextlib  # Context manager utilities for temporarily redirecting stdout
from pathlib import Path  # Object-oriented filesystem path handling

# ==========================================
# 1. PATH CONFIGURATION
# ==========================================
# Resolve the absolute directory path of this worker.py file
current_dir = Path(__file__).resolve().parent
# Add the worker's directory to Python's module search path so that
# pygreensense_lib can be imported regardless of the working directory
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

# ==========================================
# 2. IMPORTS
# ==========================================
# Try to import the required functions from the pygreensense_lib package.
# If the package is not installed or not on the path, return a JSON error
# to the VS Code extension and exit with code 1.
try:
    from pygreensense_lib.cli import (
        get_argument_parser,        # Factory for the CLI argument parser
        setup_rules,                # Creates rule instances from parsed args
        analyze_code_smells,        # Main code smell detection entry point
        count_total_loc_code_smells, # Sums lines of code affected by smells
        carbon_track                # Runs carbon emission tracking via CodeCarbon
    )
except ImportError as e:
    # Build a JSON error response that the extension can understand
    error_response = {
        "status": "error",
        "type": "ImportError",
        "message": f"Could not find library: {str(e)}",
        "hint": "Ensure 'pygreensense_lib' is installed or in the correct path."
    }
    # Print the error as JSON to stdout (the extension reads stdout)
    print(json.dumps(error_response))
    # Exit with non-zero code to signal failure
    sys.exit(1)

def main():
    """
    Main entry point for the worker process invoked by the VS Code extension.
    
    Parses CLI arguments, runs code smell analysis and carbon emission tracking,
    then outputs a structured JSON response to stdout for the extension to consume.
    Captures all stdout from sub-libraries to prevent interference with JSON output.
    """
    try:
        # =========================================================
        # 3. ARGUMENTS & SETUP
        # =========================================================
        # Create the argument parser (same one used by the CLI) and parse sys.argv
        parser = get_argument_parser()
        args = parser.parse_args()

        # Pre-process logic: handle special argument values
        # If the user passed "run" as the path, default to the current directory
        if getattr(args, 'path', None) == "run":
            args.path = "."
        
        # Configure duplicated code detection scope based on mutually exclusive flags
        if getattr(args, 'dup_check_within_only', False):
            # Only check for duplicates within individual functions
            args.dup_check_within = True
            args.dup_check_between = False
        elif getattr(args, 'dup_check_between_only', False):
            # Only check for duplicates between different functions
            args.dup_check_within = False
            args.dup_check_between = True
        else:
            # Default: check for duplicates both within and between functions
            args.dup_check_within = True
            args.dup_check_between = True

        # Validate that the target path actually exists on disk
        target_path = Path(args.path)
        if not target_path.exists():
            raise FileNotFoundError(f"Path not found: {args.path}")

        # =========================================================
        # 4. EXECUTE ANALYSIS (Silence Output)
        # =========================================================
        # Auto-enable carbon tracking if targeting a single .py file
        # and the user didn't explicitly specify --carbon-run
        if not getattr(args, 'carbon_run', None) and target_path.is_file():
            args.carbon_run = str(target_path)
        
        # If targeting a whole directory without --carbon-run,
        # cli.py will auto-detect the entry point (e.g., main.py)

        # =========================================================
        # Capture stdout to prevent print() calls in sub-libraries
        # from corrupting the JSON output sent to the extension
        # =========================================================
        captured_output = io.StringIO()
        with contextlib.redirect_stdout(captured_output):
            
            # Step 1: Run code smell analysis on the target path
            # Returns: all_results (dict: file -> issues), total_loc (int: affected lines)
            all_results, total_loc = analyze_code_smells(args.path, args)
            
            # Step 2: Run carbon emission tracking (always attempted)
            # Returns: carbon_data (dict with emission metrics) or None
            carbon_data = carbon_track(args.path, args, total_loc)

        # =========================================================
        # 5. FORMAT JSON OUTPUT
        # =========================================================
        # Convert the analysis results from dict-of-dicts to a flat list
        # of issue objects that the extension's TypeScript code expects
        json_results = []
        
        # 5.1 Format Code Smell Results
        # Iterate over each analyzed file and its list of issues
        for file_path, issues in all_results.items():
            path_str = str(file_path)  # Convert Path object to string for JSON serialization
            
            for issue in issues:
                # Build a standardized issue object matching the PyGreenSenseIssue interface
                json_results.append({
                    "file": path_str,                              # File where the issue was found
                    "rule": issue.get('rule'),                     # Rule name (e.g., "GodClass")
                    "message": issue.get('message'),               # Human-readable description
                    "lineno": issue.get('lineno'),                 # Start line number
                    "end_lineno": issue.get('end_lineno'),         # End line number
                    "severity": issue.get('severity', 'Warning')   # Severity level, default "Warning"
                })

        # 5.2 Format Carbon Report
        # Transform the raw carbon_data dict into the CarbonReport structure
        # expected by the extension's TypeScript interface
        carbon_report = None
        if carbon_data:
            carbon_report = {
                "execution_details": {
                    "target_file": carbon_data.get("target_file"),       # Which .py file was executed
                    "duration_seconds": carbon_data.get("duration_seconds") # Execution duration
                },
                "energy_and_emissions": {
                    "total_energy_consumed_kwh": carbon_data.get("energy_consumed_kWh"),        # Energy in kWh
                    "carbon_emissions_kg_co2": carbon_data.get("emission_kg"),                   # CO2 in kg
                    "emissions_rate_g_co2eq_per_kwh": carbon_data.get("emissions_rate_gCO2eq_per_kWh"), # Grid carbon intensity
                    "region": carbon_data.get("region"),                                         # Geographic region
                    "country": carbon_data.get("country_name")                                   # Country name
                },
                "code_metrics": {
                    "cosmic_function_points": carbon_data.get("cfp"),              # COSMIC CFP count
                    "total_loc_code_smells": carbon_data.get("lines_of_code")      # LOC affected by smells
                },
                "sci_metrics": {
                    "per_line_of_code_g_co2eq": carbon_data.get("sci_gCO2eq_per_line"),  # SCI per LOC
                    "per_cosmic_function_point_g_co2eq": carbon_data.get("sci_per_cfp")  # SCI per CFP
                },
                "status": carbon_data.get("status"),                     # Green status label
                "improvement_percent": carbon_data.get("improvement_percent") # % improvement vs previous
            }

        # 5.3 Construct Final Response
        # Assemble the top-level JSON envelope that the extension parses
        response = {
            "status": "success",
            "data": {
                "summary": {
                    "total_files": len(all_results),       # Number of files analyzed
                    "total_issues": len(json_results),     # Total number of issues found
                    "total_smell_loc": total_loc           # Total lines affected by smells
                },
                "results": json_results,        # Flat list of all code smell issues
                "carbon_report": carbon_report, # Carbon tracking results (or null)
            }
        }
        
        # Restore the real stdout (in case it was still redirected by contextlib)
        sys.stdout = sys.__stdout__
        # Print the JSON response to stdout for the extension to parse
        print(json.dumps(response, indent=2))

    except Exception as e:
        # On any unhandled exception, write the full traceback to stderr for debugging
        sys.stderr.write(traceback.format_exc())
        # Build an error response object
        error_res = {
            "status": "error",
            "message": str(e),
            "type": type(e).__name__
        }
        # Exit with non-zero code to signal failure to the extension
        sys.exit(1)

# Standard Python entry point guard \u2014 only run main() when executed directly
if __name__ == "__main__":
    main()