import os
import requests
from dotenv import load_dotenv

load_dotenv()

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").rstrip("/")
JIRA_TOKEN = os.getenv("JIRA_API_TOKEN") 
TEMPO_TOKEN = os.getenv("TEMPO_API_TOKEN") 

JIRA_HEADERS = {"Authorization": f"Bearer {JIRA_TOKEN}", "Content-Type": "application/json"}
TEMPO_HEADERS = {"Authorization": f"Bearer {TEMPO_TOKEN}", "Content-Type": "application/json"}

def get_tempo_accounts():
    print("--- СПИСОК АККАУНТОВ TEMPO ---")
    url = f"{JIRA_BASE_URL}/rest/tempo-accounts/1/account"
    res = requests.get(url, headers=TEMPO_HEADERS)
    
    if res.status_code == 200:
        accounts = res.json()
        for acc in accounts:
            key = acc.get("key", "UNKNOWN")
            name = acc.get("name", "Unnamed")
            status = acc.get("status", "UNKNOWN")
            if status == "OPEN": 
                print(f"Ключ: {key} \t| Название: {name}")
    else:
        print(f"Ошибка получения аккаунтов: {res.status_code} {res.text}")
    print("\n")

def get_jira_products():
    print("--- УНИКАЛЬНЫЕ ПРОДУКТЫ ИЗ PRESALE ---")
    # Убрали is not EMPTY, просто берем свежие задачи
    jql = 'project = PRESALE ORDER BY updated DESC'
    url = f"{JIRA_BASE_URL}/rest/api/2/search"
    
    res = requests.get(url, headers=JIRA_HEADERS, params={
        "jql": jql, 
        "fields": "customfield_24604", 
        "maxResults": 1000
    })
    
    if res.status_code == 200:
        issues = res.json().get("issues", [])
        unique_products = set()
        
        for issue in issues:
            product_field = issue.get("fields", {}).get("customfield_24604")
            
            # Учитываем, что поле может быть словарем, строкой или списком
            if isinstance(product_field, dict):
                unique_products.add(product_field.get("value", product_field.get("name", "")))
            elif isinstance(product_field, list) and len(product_field) > 0:
                val = product_field[0]
                if isinstance(val, dict):
                    unique_products.add(val.get("value", val.get("name", "")))
                else:
                    unique_products.add(str(val))
            elif isinstance(product_field, str):
                unique_products.add(product_field)
                
        # Фильтруем пустышки
        clean_products = [p for p in unique_products if p and str(p).strip() and str(p) != 'None']
        
        if not clean_products:
            print("🤔 Продукты не найдены. Проверьте: есть ли в последних 1000 задачах PRESALE заполненное поле customfield_24604?")
            
        for prod in sorted(clean_products):
            print(f'"{prod}"')
    else:
        print(f"🚫 Ошибка поиска в Jira: {res.status_code} {res.text}")

if __name__ == "__main__":
    get_tempo_accounts()
    get_jira_products()