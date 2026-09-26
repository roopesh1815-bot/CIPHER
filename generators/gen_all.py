r"""
CrimeNet AI — Master Data Generator
Runs all generators in correct order and produces all 4 source datasets
Usage: python generators/gen_all.py  (run from D:\crimenet-ai\)
"""

import os
import sys
import time
import subprocess

# ── Make sure we run from project root ───────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from core.config import OUTPUT_DIR, PROCESSED_DIR, RAW_DIR as CONFIG_RAW_DIR

RAW_DIR = str(CONFIG_RAW_DIR)
os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

EXPECTED_DATASETS = {
    "fir_500.csv": {
        "columns": {
            "FIR_ID", "Incident_Date", "FIR_Date", "Crime_Type", "District",
            "Complainant_Name", "Complainant_Mobile", "Victim_Name", "Victim_Mobile",
            "Suspect_Name", "Suspect_Mobile", "Associate_Name", "Associate_Mobile",
            "Witness_Name", "Witness_Mobile", "Incident_Location", "Vehicle_Number",
            "Account_Number", "FIR_Description", "Related_FIR_ID",
        },
        "rows": 500,
    },
    "cdr_logs.csv": {
        "columns": {
            "CDR_ID", "Caller_Mobile", "Callee_Mobile", "Call_Type",
            "Call_DateTime", "Duration_Sec", "Cell_Tower",
        },
        "rows": 3000,
    },
    "financial_txns.csv": {
        "columns": {
            "TXN_ID", "Sender_Account", "Receiver_Account", "Transaction_Type",
            "Amount_INR", "Transaction_DateTime", "Mobile_Ref", "Suspicious_Flag",
        },
        "rows": 2000,
    },
    "social_media.csv": {
        "columns": {
            "POST_ID", "Platform", "Handle", "Post_Text", "Post_DateTime",
            "Mentioned_Name", "Mentioned_Mobile", "Mentioned_Vehicle",
            "Mentioned_Location",
        },
        "rows": 1000,
    },
}


def banner(msg):
    print("\n" + "=" * 60)
    print(f"  {msg}")
    print("=" * 60)


def run_step(label, func):
    banner(label)
    t0 = time.time()
    try:
        func()
        elapsed = time.time() - t0
        print(f"\n  [✓] Done in {elapsed:.1f}s")
        return True
    except Exception as e:
        print(f"\n  [✗] FAILED: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# STEP 1 — FIR Dataset (copy gen_fir.py output or run it)
# ─────────────────────────────────────────────────────────────
def step_fir():
    fir_path = os.path.join(RAW_DIR, "fir_500.csv")
    if os.path.exists(fir_path):
        import pandas as pd
        df = pd.read_csv(fir_path)
        print(f"  [✓] FIR dataset already exists — {len(df)} rows")
        return

    # Try running gen_fir.py if it exists
    gen_fir = os.path.join(ROOT, "generators", "gen_fir.py")
    if os.path.exists(gen_fir) and os.path.getsize(gen_fir) > 100:
        print("  Running gen_fir.py ...")
        subprocess.run([sys.executable, gen_fir, "500",
                        os.path.join(RAW_DIR, "fir_500.csv")], check=True)
    else:
        print("  [!] fir_500.csv not found and gen_fir.py is empty.")
        print("  [!] Copy your fir_500.csv into data/raw/ and rerun.")
        print("  [!] Continuing with other generators using fallback pools.")


# ─────────────────────────────────────────────────────────────
# STEP 2 — CDR Logs
# ─────────────────────────────────────────────────────────────
def step_cdr():
    sys.path.insert(0, os.path.join(ROOT, "generators"))
    import gen_cdr
    # Override output path to be absolute
    gen_cdr.FIR_FILE    = os.path.join(RAW_DIR, "fir_500.csv")
    gen_cdr.OUTPUT_FILE = os.path.join(RAW_DIR, "cdr_logs.csv")
    gen_cdr.main()


# ─────────────────────────────────────────────────────────────
# STEP 3 — Financial Transactions
# ─────────────────────────────────────────────────────────────
def step_financial():
    import gen_financial
    gen_financial.FIR_FILE    = os.path.join(RAW_DIR, "fir_500.csv")
    gen_financial.OUTPUT_FILE = os.path.join(RAW_DIR, "financial_txns.csv")
    gen_financial.main()


# ─────────────────────────────────────────────────────────────
# STEP 4 — Social Media Posts
# ─────────────────────────────────────────────────────────────
def step_social():
    import gen_social
    gen_social.FIR_FILE    = os.path.join(RAW_DIR, "fir_500.csv")
    gen_social.OUTPUT_FILE = os.path.join(RAW_DIR, "social_media.csv")
    gen_social.main()


# ─────────────────────────────────────────────────────────────
# STEP 5 — Verify all outputs
# ─────────────────────────────────────────────────────────────
def step_verify():
    import pandas as pd
    print()
    all_ok = True
    for fname, requirements in EXPECTED_DATASETS.items():
        path = os.path.join(RAW_DIR, fname)
        if not os.path.exists(path):
            print(f"  [✗] MISSING  : {fname}")
            all_ok = False
            continue
        try:
            df = pd.read_csv(path)
            missing_columns = requirements["columns"] - set(df.columns)
            sufficient_rows = len(df) >= requirements["rows"]
            valid = not missing_columns and sufficient_rows
            status = "✓" if valid else "✗"
            size_kb = os.path.getsize(path) // 1024
            print(
                f"  [{status}] {fname:<25} {len(df):>5}/{requirements['rows']} rows"
                f"   {size_kb:>5} KB"
            )
            if missing_columns:
                print(f"      Missing columns: {', '.join(sorted(missing_columns))}")
            if not sufficient_rows:
                print(f"      Expected at least {requirements['rows']} rows")
            all_ok = all_ok and valid
        except Exception as e:
            print(f"  [✗] ERROR reading {fname}: {e}")
            all_ok = False

    if all_ok:
        print("\n  [✓] All datasets verified — ready for pipeline!")
    else:
        print("\n  [!] Some files missing — check warnings above.")
        raise RuntimeError("Dataset verification failed")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "█" * 60)
    print("  CrimeNet AI — Master Data Generator")
    print("  Team: ShadowLink | PS-26189")
    print("█" * 60)

    total_start = time.time()
    results = []

    results.append(run_step("STEP 1 — FIR Dataset",              step_fir))
    results.append(run_step("STEP 2 — CDR Logs (3,000 records)", step_cdr))
    results.append(run_step("STEP 3 — Financial Txns (2,000)",   step_financial))
    results.append(run_step("STEP 4 — Social Media (1,000 posts)", step_social))
    results.append(run_step("STEP 5 — Verify All Outputs",       step_verify))

    total = time.time() - total_start
    passed = sum(results)

    print("\n" + "█" * 60)
    print(f"  {passed}/{len(results)} steps completed in {total:.1f}s")
    if passed == len(results):
        print("  STATUS: ALL DATASETS READY")
        print()
        print("  Next step:")
        print("  python pipeline/run_pipeline.py")
    else:
        print("  STATUS: SOME STEPS FAILED — check output above")
    print("█" * 60 + "\n")
