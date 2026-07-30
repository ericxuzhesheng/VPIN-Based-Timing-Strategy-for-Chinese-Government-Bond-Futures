#!/usr/bin/env bash
#
# Daily update entry point for GitHub Actions.
# Runs: data refresh → VPIN pipeline → report update.
# Logs everything to scripts/logs/daily-update-YYYYMMDD.log.
#

set -euo pipefail

TIMESTAMP=$(TZ='Asia/Shanghai' date '+%Y%m%d')
LOG_DIR="scripts/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/daily-update-$TIMESTAMP.log"

# Redirect all output to both console and log file
exec > >(tee -a "$LOG_FILE") 2>&1

log_step() {
    echo ""
    echo "============================================================"
    echo "  $1"
    echo "  $(TZ='Asia/Shanghai' date '+%Y-%m-%d %H:%M:%S CST')"
    echo "============================================================"
}

log_step "STEP 1/3: Refresh market data (Tushare + AKShare)"
END_DATE_ARG=""
if [[ -n "${GITHUB_EVENT_INPUTS_END_DATE:-}" ]]; then
    END_DATE_ARG="--end-date ${GITHUB_EVENT_INPUTS_END_DATE}"
fi
python update_market_data.py $END_DATE_ARG
echo "✓ Market data refresh complete."

log_step "STEP 2/3: Run VPIN timing pipeline"
python vpin_timing.py
echo "✓ VPIN pipeline complete."

log_step "STEP 3/3: Update research report"
python scripts/update_report.py
echo "✓ Report update complete."

log_step "DAILY UPDATE FINISHED"
echo "Log saved to: $LOG_FILE"
