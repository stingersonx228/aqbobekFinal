import google.generativeai as genai

GEMINI_KEY = "AIzaSyBS2X7rXe207ZT_ez0wr-ogaLj2b8SRurI"
genai.configure(api_key=GEMINI_KEY)

print("Available models:")
for model in genai.list_models():
    print(f"  - {model.name}")
    print(f"    Display name: {model.display_name}")
    print(f"    Supported methods: {model.supported_generation_methods}")
    print()
