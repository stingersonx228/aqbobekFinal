import fitz
import sys

def extract_text(pdf_path, output_path):
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text()
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Successfully extracted text to {output_path}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    pdf_file = "ТЕХНИЧЕСКОЕ ЗАДАНИЕ (ПАСПОРТ КЕЙСА №2) (1).pdf"
    output_file = "scratch/new_tz.txt"
    extract_text(pdf_file, output_file)
