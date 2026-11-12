"""Print Locust's CSV statistics as a Markdown table (for the thesis).

    python loadtest/summary.py loadtest-results_stats.csv
"""

import csv
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "loadtest-results_stats.csv"

with open(path, newline="", encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle))

print("| Request | Requests | Failures | Median ms | 95% ms | Max ms | Req/s |")
print("|---|---:|---:|---:|---:|---:|---:|")
for row in rows:
    name = row["Name"] if row["Name"] != "Aggregated" else "**All requests**"
    print(
        f"| {name} | {row['Request Count']} | {row['Failure Count']} | {row['Median Response Time']} | "
        f"{row['95%']} | {float(row['Max Response Time']):.0f} | {float(row['Requests/s']):.1f} |"
    )
