import pandas as pd
import glob
import os

# Find the excel file
files = glob.glob("*.xlsx")
target = None
for f in files:
    if "2025-2026" in f:
        target = f
        break

if target:
    output = []
    output.append(f"Reading file: {target}")
    xl = pd.ExcelFile(target)
    output.append(f"Sheets: {xl.sheet_names}")
    
    for sheet in xl.sheet_names:
        output.append(f"\n--- Sheet: {sheet} ---")
        df = pd.read_excel(target, sheet_name=sheet).head(20)
        output.append(df.to_string())
    
    with open("scratch/excel_analysis.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(output))
    print("Analysis saved to scratch/excel_analysis.txt")
else:
    print("Excel file not found.")
