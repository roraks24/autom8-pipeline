import time
import sys
from daily_workflow import run_daily_workflow

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def main():
    print("=" * 70)
    print("           STARTING DUAL PIPELINE EXECUTION (RUN 1 OF 2)")
    print("=" * 70)
    run_daily_workflow(submit=True)

    print("\n" + "=" * 70)
    print("   RUN 1 FINISHED! STARTING RUN 2 OF 2 (NEXT BATCH ON WELLFOUND & INTERNSHALA)")
    print("=" * 70)
    time.sleep(5)
    run_daily_workflow(submit=True)

    print("\n" + "=" * 70)
    print("           BOTH PIPELINE RUNS COMPLETED SUCCESSFULLY!")
    print("=" * 70)

if __name__ == "__main__":
    main()
