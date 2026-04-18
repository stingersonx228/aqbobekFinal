import sqlite3
import pandas as pd

conn = sqlite3.connect('aqbobek.db')
query = "SELECT * FROM subjects"
df = pd.read_sql_query(query, conn)

with open('scratch/duplicate_analysis.txt', 'w', encoding='utf-8') as f:
    f.write("--- All Subjects ---\n")
    f.write(df.to_string())
    f.write("\n\n")

    duplicates = df[df.duplicated('name', keep=False)]
    if not duplicates.empty:
        f.write("--- Duplicate Subjects Found ---\n")
        f.write(duplicates.to_string())
        f.write("\n\n")
    else:
        f.write("No exact duplicates found in 'name' column.\n\n")

    # Check for case-insensitive duplicates
    df['name_lower'] = df['name'].str.lower().str.strip()
    duplicates_ci = df[df.duplicated('name_lower', keep=False)]
    if not duplicates_ci.empty:
        f.write("--- Case-Insensitive Duplicate Subjects Found ---\n")
        f.write(duplicates_ci.to_string())
    else:
        f.write("No case-insensitive duplicates found.\n")

conn.close()
