import fitz
import glob

# Find the file that starts with ТЗ or TZ
files = glob.glob('**.pdf') + glob.glob('*ТЗ*.pdf')
for f in files:
    if "2" in f and "1" in f:
        doc = fitz.open(f)
        text = '\n'.join([page.get_text() for page in doc])
        with open('tz_extracted.txt', 'w', encoding='utf-8') as out:
            out.write(text)
        print("Success:", f)
        break
