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
        if getattr(args, 'path', None) == "run":
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
        
        # =========================================================
        # 🌟 จุดที่เพิ่มใหม่: บังคับรัน Carbon อัตโนมัติ
        # ถ้า target_path เป็นไฟล์ (.py) ให้เอาไฟล์นั้นไปรันวัดคาร์บอนเลย
        # โดยไม่ต้องรอให้ผู้ใช้พิมพ์ --carbon-run
        # =========================================================
        if not getattr(args, 'carbon_run', None) and target_path.is_file():
            args.carbon_run = str(target_path)
        
        # ถ้ารันทั้งโฟลเดอร์ (.) แล้วไม่ได้ใส่ --carbon-run จะปล่อยให้ 
        # cli.py จัดการหา Entry point (main.py) เอง

        # =========================================================
        # จับ Output เพื่อไม่ให้ Text ขยะปนกับ JSON
        # =========================================================
        captured_output = io.StringIO()
        with contextlib.redirect_stdout(captured_output):
            
            # 1. รันหา Code Smells
            all_results, total_loc = analyze_code_smells(args.path, args)
            
            # 2. รันหา Carbon เสมอ
            # (ตอนนี้ args.carbon_run จะมีค่าเป็น 'bad_code.py' แล้ว)
            carbon_data = carbon_track(args.path, args, total_loc)

        # =========================================================
        # 5. FORMAT JSON OUTPUT
        # =========================================================
        # เปลี่ยนจาก Dict {} เป็น List [] เพื่อให้เหมือน pygreensense CLI output
        json_results = []
        
        # 5.1 Format Code Smell Results
        for file_path, issues in all_results.items():
            path_str = str(file_path)
            
            for issue in issues:
                # สร้าง Object ที่หน้าตาเหมือน pygreensense output เป๊ะๆ
                json_results.append({
                    "file": path_str,  # เพิ่ม Key 'file' เข้าไปใน object
                    "rule": issue.get('rule'),
                    "message": issue.get('message'),
                    "lineno": issue.get('lineno'),
                    "end_lineno": issue.get('end_lineno'),
                    "severity": issue.get('severity', 'Warning')
                })

        # 5.2 Format Carbon Report (เหมือนเดิม)
        carbon_report = None
        if carbon_data:
            carbon_report = {
                # ... (คงโค้ดเดิมไว้) ...
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
                    # นับจำนวน issues จาก list โดยตรง
                    "total_issues": len(json_results),
                    "total_smell_loc": total_loc
                },
                "results": json_results, # ตรงนี้จะเป็น List แล้ว
                "carbon_report": carbon_report,
            }
        }
        
        # Print JSON Output (ใช้เทคนิคแก้ Dirty Stdout ที่แนะนำไปก่อนหน้า)
        sys.stdout = sys.__stdout__ # หรือตัวแปร real_stdout ถ้าคุณเก็บไว้
        print(json.dumps(response, indent=2))

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