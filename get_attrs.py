import os
import requests
from dotenv import load_dotenv

load_dotenv()

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").rstrip("/")
TEMPO_TOKEN = os.getenv("TEMPO_API_TOKEN") 
TEMPO_HEADERS = {"Authorization": f"Bearer {TEMPO_TOKEN}", "Content-Type": "application/json"}

print("--- СПИСОК АТРИБУТОВ ВОРКЛОГА TEMPO ---")
url = f"{JIRA_BASE_URL}/rest/tempo-timesheets/4/work-attributes"
res = requests.get(url, headers=TEMPO_HEADERS)

if res.status_code == 200:
    for attr in res.json():
        print(f"Название: {attr.get('name')} | Ключ: {attr.get('key')} | Тип: {attr.get('type')}")
else:
    print(f"Ошибка: {res.status_code} {res.text}")