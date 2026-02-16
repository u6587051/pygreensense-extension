import sys
import json
import traceback
import io
import contextlib
from pathlib import Path

# ==========================================
# 1. PATH CONFIGURATION
# ==========================================
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

# ==========================================
# 2. IMPORTS
# ==========================================
try:
    from pygreensense_lib.cli import (
        get_argument_parser, 
        setup_rules, 
        analyze_code_smells, 
        count_total_loc_code_smells,
        carbon_track  # Import ฟังก์ชันนี้มาด้วย
    )
except ImportError as e:
    error_response = {
        "status": "error",
        "type": "ImportError",
        "message": f"Could not find library: {str(e)}",
        "hint": "Ensure 'pygreensense_lib' is installed or in the correct path."
    }
    print(json.dumps(error_response))
    sys.exit(1)

def main():
    try:
        # =========================================================
        # 3. ARGUMENTS & SETUP
        # =========================================================
        parser = get_argument_parser()
        args = parser.parse_args()

        # Pre-process logic (เหมือน cli.py)
        if args.path == "run":
            args.path = "."
            
        if getattr(args, 'dup_check_within_only', False):
            args.dup_check_within = True
            args.dup_check_between = False
        elif getattr(args, 'dup_check_between_only', False):
            args.dup_check_within = False
            args.dup_check_between = True
        else:
            args.dup_check_within = True
            args.dup_check_between = True

        target_path = Path(args.path)
        if not target_path.exists():
            raise FileNotFoundError(f"Path not found: {args.path}")

        # =========================================================
        # 4. EXECUTE ANALYSIS (Silence Output)
        # =========================================================
        # ใช้ StringIO เพื่อดักจับ Text ที่ cli.py อาจจะ print ออกมา (ไม่ให้ปนกับ JSON)
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            # 4.1 Run Code Smell Analysis
            all_results, total_loc = analyze_code_smells(args.path, args)
            
            # 4.2 Run Carbon Tracking (เรียกใช้ฟังก์ชันที่เราเพิ่งแก้ให้ return ค่า)
            carbon_data = carbon_track(args.path, args, total_loc)

        # =========================================================
        # 5. FORMAT JSON OUTPUT
        # =========================================================
        json_results = {}
        
        # 5.1 Format Code Smell Results
        for file_path, issues in all_results.items():
            path_str = str(file_path)
            if path_str not in json_results:
                json_results[path_str] = []
            
            for issue in issues:
                json_results[path_str].append({
                    "rule": issue.get('rule'),
                    "message": issue.get('message'),
                    "lineno": issue.get('lineno'),
                    "end_lineno": issue.get('end_lineno'),
                    "severity": issue.get('severity', 'Warning')
                })

        # 5.2 Format Carbon Report (Map ข้อมูลตามที่คุณขอ)
        carbon_report = None
        if carbon_data:
            carbon_report = {
                "execution_details": {
                    "target_file": carbon_data.get("target_file"),
                    "duration_seconds": carbon_data.get("duration_seconds")
                },
                "energy_and_emissions": {
                    "total_energy_consumed_kwh": carbon_data.get("energy_consumed_kWh"),
                    "carbon_emissions_kg_co2": carbon_data.get("emission_kg"),
                    "emissions_rate_g_co2eq_per_kwh": carbon_data.get("emissions_rate_gCO2eq_per_kWh"),
                    "region": carbon_data.get("region"),
                    "country": carbon_data.get("country_name")
                },
                "code_metrics": {
                    "cosmic_function_points": carbon_data.get("cfp"),
                    "total_loc_code_smells": carbon_data.get("lines_of_code")
                },
                "sci_metrics": {
                    "per_line_of_code_g_co2eq": carbon_data.get("sci_gCO2eq_per_line"),
                    "per_cosmic_function_point_g_co2eq": carbon_data.get("sci_per_cfp")
                },
                "status": carbon_data.get("status"),
                "improvement_percent": carbon_data.get("improvement_percent")
            }

        # 5.3 Construct Final Response
        response = {
            "status": "success",
            "data": {
                "summary": {
                    "total_files": len(all_results),
                    "total_issues": sum(len(i) for i in all_results.values()),
                    "total_smell_loc": total_loc
                },
                "results": json_results,
                # "carbon_report": carbon_report,  # ✅ เพิ่มส่วนนี้เข้ามา
            }
        }
        
        # Print JSON Output
        # print(json.dumps(response, indent=2))

    except Exception as e:
        sys.stderr.write(traceback.format_exc())
        error_res = {
            "status": "error",
            "message": str(e),
            "type": type(e).__name__
        }
        # print(json.dumps(error_res))
        sys.exit(1)

if __name__ == "__main__":
    main()