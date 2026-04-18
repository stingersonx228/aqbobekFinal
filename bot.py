import sys
import telebot
import google.generativeai as genai
import json
import re
import logging

# Включаем логирование для telebot
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("bot")
logger.setLevel(logging.DEBUG)

# Настройки
TG_TOKEN = "8642572783:AAHNR5N9QU6gVpo_EcL2c5QmF0N1Kfos6ms"
GEMINI_KEY = "AIzaSyBS2X7rXe207ZT_ez0wr-ogaLj2b8SRurI"
TOTAL_STUDENTS = 400  # Всего детей в школе

# Инициализируем Gemini
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

bot = telebot.TeleBot(TG_TOKEN)

# --- Имитация Базы Данных (на хакатоне замени на PostgreSQL или TinyDB) ---
db = {
    "absent": 0,  # Общее число отсутствующих в школе
    "incidents": [], # Список заявок для завхоза
    "tasks": [] # Задачи для учителей
}

SYSTEM_PROMPT = """You are a strict message classification system.

Task: Analyze the input message and return ONLY a valid JSON object.
Do NOT include any explanations, comments, or extra text.
Do NOT use markdown. Output must be pure JSON.

Categories:

1. canteen — Reports about student attendance affecting meals.
Required fields:
- class (string)
- total (number)
- sick (number)

Example:
{"type":"canteen","class":"10A","total":24,"sick":5}

2. incident — Reports of damage or broken items.
Required fields:
- location (string)
- issue (string)

Example:
{"type":"incident","location":"room 203","issue":"desk broken"}

3. task — Instructions or assignments for staff.
Required fields:
- assignee (string)
- action (string)

Example:
{"type":"task","assignee":"teacher","action":"prepare homework"}

4. spam — Any message that does not match the above categories.

Example:
{"type":"spam"}

Rules:
- Always return exactly one JSON object
- No extra text under any circumstances
- If required data is missing and cannot be inferred, return {"type":"spam"}
- Keep values short and normalized."""

# --- Функции для сохранения (твои "ветки" из схемы) ---

def save_canteen_data(data):
    # Добавляем число отсутствующих к общему счетчику
    absent_count = data.get('sick', 0)
    db["absent"] += absent_count
    present_count = TOTAL_STUDENTS - db["absent"]
    return f"[SCHOOL] {absent_count} students absent. Total absent today: {db['absent']}. Present at school: {present_count}"

def save_incident(data):
    # Красная ветка: Завхоз увидит это на Дашборде
    db["incidents"].append(data)
    location = data.get('location', 'unknown')
    issue = data.get('issue', 'unknown')
    return f"[INCIDENT REPORT] Location: {location} | Issue: {issue} | Manager notified!"

def save_task(data):
    # Синяя ветка: Постановка задач
    db["tasks"].append(data)
    return f"[TASK] Created for {data.get('assignee')}: {data.get('action')}"

def extract_with_gemini(text):
    # СНАЧАЛА проверяем на инцидент - это приоритет!
    # Паттерны для инцидентов: поломки, потери, ущерб, кража, драки и т.д.
    incident_keywords = r'(сломал|поломал|разбил|сломлась|сломалась|сломалось|сломано|поломк|повреждени|потеря|потеря|кража|украл|украд|порвал|порванное|разорвал|испортил|испортилось|затопил|утеч|утечка|пожар|пожарище|дрался|драка|драк|дралис|побоище|избил|побили|окровавлен|кровь|ранен|травмирован|конфликт|ссора|поругались)'
    
    if re.search(incident_keywords, text, re.IGNORECASE):
        # Пробуем извлечь явно указанную локацию (кабинет, столовая, спортзал и т.д.)
        location_keywords = {
            'кабинет': r'(кабинет|каб\.|в\s+каб\.?)\s+([0-9]+)',
            'столовая': r'(столов|столовой|сто)',
            'спортзал': r'(спортзал|спортзалом|спортивном)',
            'коридор': r'(коридор|коридорах)',
            'лестница': r'(лестниц|лестнице)',
            'раздевалка': r'(раздевалк)',
            'библиотека': r'(библиотек)',
            'актовый зал': r'(актовый|актов)',
            'двор': r'(двор|дворе)',
            'стадион': r'(стадион|стадионе)',
            'туалет': r'(туалет|туалетн)',
            'медпункт': r'(медпункт|кабинет\s+медсестр)',
            'кровля': r'(крыша|кровля)',
            'подвал': r'(подвал|подвалом)',
        }
        
        location = "unknown"
        for loc_name, pattern in location_keywords.items():
            if re.search(pattern, text, re.IGNORECASE):
                location = loc_name
                # Пробуем извлечь номер кабинета если есть
                if loc_name == 'кабинет':
                    num_match = re.search(pattern, text, re.IGNORECASE)
                    if num_match and num_match.group(2):
                        location = f"кабинет {num_match.group(2)}"
                break
        
        print(f"[AI_LOCAL] Инцидент локация: {location}")
        
        # Пробуем извлечь что конкретно произошло
        issue_keywords = {
            'парта': r'(парта|стол)',
            'окно': r'(окно|стекло)',
            'дверь': r'(дверь|двер)',
            'стул': r'(стул|кресло)',
            'доска': r'(доска|классная)',
            'кровля': r'(крыша|кровля)',
            'труба': r'(труб|канализция)',
            'электричество': r'(про|провод|электро|розетка)',
            'имущество': r'(имущество|вещь|личное)',
            'драка': r'(дрался|драка|драк|дралис|побоище|избил|побили|окровавлен|кровь|ранен|травмирован)',
            'конфликт': r'(конфликт|ссора|поругались|скандал)',
            'другое': ''
        }
        
        issue = "unknown"
        for damage_type, pattern in issue_keywords.items():
            if pattern and re.search(pattern, text, re.IGNORECASE):
                issue = damage_type
                break
        
        print(f"[AI_LOCAL] Инцидент тип: {issue}")
        return {"type": "incident", "location": location, "issue": issue}
    
    # ПОТОМ проверяем на отсутствующих иначе числа типа 212 (номер кабинета) будут распознаны неправильно
    # Вариант 1: "Класс нету N детей" - "6С нету 2 детей", "10А нету 5"
    class_match = re.search(r'([0-9]{1,2}\s*[А-Я])\s+(нету|нет)\s+([0-9]+)', text, re.IGNORECASE)
    if class_match:
        absent_count = int(class_match.group(3))
        print(f"[AI_LOCAL] Парсер 1: класс нету число: {absent_count} дет")
        return {"type": "canteen", "class": "school", "total": 0, "sick": absent_count}
    
    # Вариант 2: "N детей нету/нет/не пришли/отсутствуют/болеют"
    simple_match = re.search(r'([0-9]+)\s+дет(ей)?.*?(нету|нет|не\s+приш|отсутств|боле)', text, re.IGNORECASE)
    if simple_match:
        absent_count = int(simple_match.group(1))
        print(f"[AI_LOCAL] Парсер 2: число дет [вариант]: {absent_count} дет")
        return {"type": "canteen", "class": "school", "total": 0, "sick": absent_count}
    
    # Вариант 3: Просто число в начале с ключевыми словами типа "2 не пришло", "5 отсутствуют"
    digit_first = re.search(r'^([0-9]+)\s+(дет|ребёнк|школьник|человек)?.*?(нету|нет|не\s+приш|отсутс|болеют|на\s+болл)', text, re.IGNORECASE)
    if digit_first:
        absent_count = int(digit_first.group(1))
        print(f"[AI_LOCAL] Парсер 3: число в начале: {absent_count} дет")
        return {"type": "canteen", "class": "school", "total": 0, "sick": absent_count}
    
    # Вариант 4: "[класс] отсутствуют N" или "[класс] болеют N"
    reverse_match = re.search(r'([0-9]{1,2}\s*[А-Я]).*?(отсутств|болеют|не\s+приш).*?([0-9]+)', text, re.IGNORECASE)
    if reverse_match:
        absent_count = int(reverse_match.group(3))
        print(f"[AI_LOCAL] Парсер 4: обратный порядок: {absent_count} дет")
        return {"type": "canteen", "class": "school", "total": 0, "sick": absent_count}
    
    # Если локальные парсеры не сработали - обращаемся к Gemini
    try:
        print(f"[AI_CALL] Запрашиваю Gemini: {text[:50]}...")
        response = model.generate_content(f"{SYSTEM_PROMPT}\n\nText: {text}")
        raw_response = response.text
        print(f"[AI_RAW] Gemini ответил: {raw_response[:100]}")
        
        raw_text = raw_response.replace('```json', '').replace('```', '').replace('json', '').strip()
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        
        if json_match:
            parsed = json.loads(json_match.group())
            print(f"[AI_PARSED] Gemini: {parsed}")
            return parsed
        else:
            print(f"[AI_WARN] JSON не найден")
            return {"type": "spam"}
    except json.JSONDecodeError as e:
        print(f"[AI_JSON_ERROR] JSON ошибка: {e}")
        return {"type": "spam"}
    except Exception as e:
        print(f"[AI_ERROR] Ошибка: {type(e).__name__}: {str(e)[:100]}")
        return {"type": "spam"}
@bot.message_handler(commands=['report'])
def send_report(message):
    present_count = TOTAL_STUDENTS - db["absent"]
    report = f"""[SCHOOL REPORT]
Total students: {TOTAL_STUDENTS}
Present at school: {present_count}
Absent: {db["absent"]}"""
    bot.send_message(message.chat.id, report)

    
@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    try:
        print(f"[MSG] Получено от {message.from_user.first_name}: {message.text}")
        
        # 1. Пропускаем через ИИ-воронку
        data = extract_with_gemini(message.text)
        print(f"[AI] Классифицировано как: {data}")
        data_type = data.get("type")
        
        reply_text = None

        # 2. Роутинг согласно твоей схеме
        if data_type == "canteen":
            reply_text = save_canteen_data(data)
            
        elif data_type == "incident":
            reply_text = save_incident(data)
            
        elif data_type == "task":
            reply_text = save_task(data)
            
        elif data_type == "spam":
            # Если это просто флуд, бот отвечает вежливо
            reply_text = "Hi! I'm the school's AI assistant. Send me info about meals, incidents, or tasks."

        if reply_text:
            print(f"[REPLY] {reply_text}")
            bot.reply_to(message, reply_text)
    except Exception as e:
        print(f"[ERROR] Ошибка при обработке сообщения: {e}")
        bot.reply_to(message, f"[ERROR] {str(e)[:100]}")

# --- Дополнительно: Команда для директора, чтобы глянуть отчет ---


print("ИИ-завуч Aqbobek запущен и готов фильтровать чат...")
print(f"[BOT] Telegram TOKEN: {TG_TOKEN[:20]}...")
print(f"[BOT] Gemini KEY: {GEMINI_KEY[:20]}...")
sys.stdout.flush()
try:
    print("[BOT] Ждём сообщений...")
    sys.stdout.flush()
    bot.infinity_polling()
except Exception as e:
    print(f"[ERROR] Ошибка при polling: {e}")
    sys.stdout.flush()