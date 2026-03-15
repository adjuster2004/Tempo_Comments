import os
import json
import requests
import re
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Загружаем конфиг
load_dotenv()

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").rstrip("/")
JIRA_TOKEN = os.getenv("JIRA_API_TOKEN") 
TEMPO_TOKEN = os.getenv("TEMPO_API_TOKEN") 

MATTERMOST_WEBHOOK_URL = os.getenv("MATTERMOST_WEBHOOK_URL", "")
MATTERMOST_DEFAULT_CHANNEL = os.getenv("MATTERMOST_DEFAULT_CHANNEL", "")
MATTERMOST_USERNAME = os.getenv("MATTERMOST_USERNAME", "Tempo_Comments")

# Загружаем списки пользователей и фильтруем тех, кто с восклицательным знаком
RAW_USERS = [u.strip() for u in os.getenv("TARGET_USERS", "").split(",") if u.strip()]
TARGET_USERS = [u for u in RAW_USERS if not u.startswith("!")]
EXCLUDED_USERS = [u.lstrip("!") for u in RAW_USERS if u.startswith("!")]

TARGET_TEAMS = [t.strip() for t in os.getenv("TARGET_TEAMS", "").split(",") if t.strip()]

MEETING_ISSUE_KEY = os.getenv("MEETING_ISSUE_KEY", "LIFE-5")
MEETING_ACCOUNT_KEY = os.getenv("MEETING_ACCOUNT_KEY", "lo-14")
MONDAY_EXCLUDE_USERS = [u.strip() for u in os.getenv("MONDAY_EXCLUDE_USERS", "").split(",") if u.strip()]

TARGET_PROJECTS = os.getenv("TARGET_PROJECTS", "")
AUTO_TAG = os.getenv("AUTO_TAG", "[AUTO]")
DEFAULT_TIME_SPENT = int(os.getenv("DEFAULT_TIME_SPENT_SECONDS", 300))
DEBUG_MODE = os.getenv("DEBUG_MODE", "False").lower() in ("true", "1", "yes")

JIRA_HEADERS = {
    "Authorization": f"Bearer {JIRA_TOKEN}",
    "Content-Type": "application/json"
}

TEMPO_HEADERS = {
    "Authorization": f"Bearer {TEMPO_TOKEN}",
    "Content-Type": "application/json"
}

# Читаем маппинг продуктов из .env
try:
    map_str = os.getenv("PRODUCT_ACCOUNT_MAP", "{}")
    PRODUCT_ACCOUNT_MAP = json.loads(map_str)
except json.JSONDecodeError:
    print("🚫 Ошибка: Неверный формат PRODUCT_ACCOUNT_MAP в .env. Ожидается валидный JSON.")
    PRODUCT_ACCOUNT_MAP = {}

def parse_time_to_seconds(time_str):
    """Парсит человекочитаемое время в секунды (например, '1.5 часа', '30 мин', '1h 30m')."""
    time_str = str(time_str).lower().strip()
    
    match_decimal = re.match(r'^([\d\.,]+)\s*(час|ч|h|hour)', time_str)
    if match_decimal:
        val = float(match_decimal.group(1).replace(',', '.'))
        return int(val * 3600)
        
    hours = 0
    minutes = 0
    
    h_match = re.search(r'(\d+)\s*(час|ч|h)', time_str)
    if h_match:
        hours = int(h_match.group(1))
        
    m_match = re.search(r'(\d+)\s*(мин|м|m)', time_str)
    if m_match:
        minutes = int(m_match.group(1))
        
    total_seconds = (hours * 3600) + (minutes * 60)
    return total_seconds if total_seconds > 0 else None

def process_comment_body(raw_body, default_product, project_key):
    """Извлекает теги продукта и времени из комментария."""
    lines = raw_body.strip().split('\n')
    non_empty_lines = [line.strip() for line in lines if line.strip()]
    
    # 1. ПРОВЕРКА: Пользователь написал только время в первой строке
    if non_empty_lines:
        time_only = parse_time_to_seconds(non_empty_lines[0])
        if time_only:
            cut_idx = 0
            for i, line in enumerate(lines):
                if line.strip():
                    cut_idx = i + 1
                    break
            clean_body = '\n'.join(lines[cut_idx:]).strip()
            if not clean_body:
                clean_body = "Ворклог"
                
            prod = None if project_key == "INT" else default_product
            print(f"🎯 УСПЕШНО: Найдено только время: {time_only} сек. Продукт опущен.")
            return prod, time_only, clean_body

    # 2. ПРОВЕРКА: Стандартный поиск Продукт + Время
    if len(non_empty_lines) >= 2:
        potential_product = non_empty_lines[0]
        potential_time = non_empty_lines[1]
        
        product_match = None
        
        for p, acc in PRODUCT_ACCOUNT_MAP.items():
            if potential_product.lower() == acc.lower():
                product_match = p
                break
                
        if not product_match:
            for p in PRODUCT_ACCOUNT_MAP.keys():
                if potential_product.lower() in p.lower():
                    product_match = p
                    break
                    
        if product_match:
            parsed_time = parse_time_to_seconds(potential_time)
            if parsed_time:
                found_count = 0
                cut_idx = 0
                for i, line in enumerate(lines):
                    if line.strip():
                        found_count += 1
                    if found_count == 2:
                        cut_idx = i + 1
                        break
                        
                clean_body = '\n'.join(lines[cut_idx:]).strip()
                if not clean_body:
                    clean_body = f"Ворклог для продукта {product_match}"
                    
                print(f"🎯 УСПЕШНО РАСПОЗНАНЫ ТЕГИ: Продукт '{product_match}', Время: {parsed_time} сек.")
                return product_match, parsed_time, clean_body
            else:
                print(f"⚠️ ТЕГИ ОТКЛОНЕНЫ: Продукт '{potential_product}' найден, но время '{potential_time}' не распознано.")
        else:
            print(f"⚠️ ТЕГИ ОТКЛОНЕНЫ: Строка '{potential_product}' не найдена ни в словаре, ни в ключах.")
            
    # 3. ЕСЛИ ТЕГОВ НЕТ: применяем дефолтные правила
    if project_key == "INT":
        return None, DEFAULT_TIME_SPENT, raw_body.strip()
        
    return default_product, DEFAULT_TIME_SPENT, raw_body.strip()

def parse_jira_date(date_str):
    if not date_str or str(date_str) in ['None', '']:
        return None
        
    date_str = str(date_str).strip().lower()

    if "-" in date_str:
        try: return datetime.strptime(date_str[:10], "%Y-%m-%d")
        except ValueError: pass

    if "." in date_str:
        try: return datetime.strptime(date_str[:10], "%d.%m.%Y")
        except ValueError: pass
            
    if "/" in date_str and date_str[:4].isdigit():
        try: return datetime.strptime(date_str[:10], "%Y/%m/%d")
        except ValueError: pass

    months = {
        "янв": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "мая": 5, "июн": 6,
        "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12
    }
    
    try:
        parts = date_str.split("/")
        if len(parts) == 3:
            day = int(parts[0])
            month_str = parts[1]
            month = None
            for k, v in months.items():
                if month_str.startswith(k):
                    month = v
                    break
            if month:
                year_str = parts[2][:2] if len(parts[2]) > 2 else parts[2]
                year = int(year_str)
                if year < 100: year += 2000
                return datetime(year, month, day)
    except Exception:
        pass
        
    return None

def get_team_members():
    team_users = {} 
    
    if not TARGET_TEAMS:
        return team_users
        
    print(f"\nИщем команды в Tempo: {TARGET_TEAMS}")
    
    teams_url = f"{JIRA_BASE_URL}/rest/tempo-teams/2/team"
    response = requests.get(teams_url, headers=TEMPO_HEADERS)
    
    if response.status_code != 200:
        print(f"🚫 Ошибка при получении списка команд. Статус: {response.status_code}")
        return team_users
        
    all_teams = response.json()
    target_teams_lower = [t.lower() for t in TARGET_TEAMS]
    
    found_team_ids = []
    for team in all_teams:
        if team.get("name", "").lower() in target_teams_lower:
            found_team_ids.append((team["id"], team["name"]))
            
    if not found_team_ids:
        print("🤔 Указанные команды не найдены в Tempo.")
        return team_users
        
    now = datetime.now()
        
    for team_id, team_name in found_team_ids:
        print(f"Загружаем участников команды '{team_name}' (ID: {team_id})...")
        members_url = f"{JIRA_BASE_URL}/rest/tempo-teams/2/team/{team_id}/member"
        m_response = requests.get(members_url, headers=TEMPO_HEADERS)
        
        if m_response.status_code == 200:
            members_data = m_response.json()
            active_team_members = set() 
            
            for m in members_data:
                member_name = m.get("member", {}).get("name")
                if not member_name: 
                    continue
                    
                membership = m.get("membership", {})
                raw_from = membership.get("dateFromANSI") or membership.get("dateFrom") or m.get("dateFrom")
                raw_to = membership.get("dateToANSI") or membership.get("dateTo") or m.get("dateTo")
                
                start_dt = parse_jira_date(raw_from) if raw_from else datetime.min
                if not start_dt: 
                    start_dt = datetime.min
                    
                end_dt_parsed = parse_jira_date(raw_to) if raw_to else None
                end_dt = end_dt_parsed.replace(hour=23, minute=59, second=59) if end_dt_parsed else datetime.max
                
                if member_name not in team_users: 
                    team_users[member_name] = []
                team_users[member_name].append((start_dt, end_dt))
                
                if start_dt <= now <= end_dt:
                    if member_name not in EXCLUDED_USERS:
                        active_team_members.add(member_name)
                
            print(f"  -> Всего записей об участии: {len(members_data)}")
            if active_team_members:
                print(f"  -> Текущий активный состав: {', '.join(sorted(active_team_members))}") 
        else:
            print(f"🚫 Ошибка получения участников: {m_response.status_code}")
            
    if team_users:
        active_overall = set()
        for user, intervals in team_users.items():
            if any(start <= now <= end for start, end in intervals):
                active_overall.add(user)
        print(f"\nВсего активных участников из команд: {len(active_overall)}")
            
    return team_users

def is_valid_author(author, comment_time, team_users):
    if author in TARGET_USERS: 
        return True
    if author in team_users:
        for start_dt, end_dt in team_users[author]:
            if start_dt <= comment_time <= end_dt: 
                return True
    return False

def get_recent_jira_comments(team_users):
    if TARGET_PROJECTS:
        projects_list = [f'"{p.strip()}"' for p in TARGET_PROJECTS.split(",") if p.strip()]
        projects_jql = ",".join(projects_list)
        jql = f'project in ({projects_jql}) AND updated >= "-24h"'
    else:
        jql = 'updated >= "-24h"'
        
    print(f"Выполняем JQL запрос: {jql}")
    
    response = requests.get(
        f"{JIRA_BASE_URL}/rest/api/2/search",
        headers=JIRA_HEADERS,
        params={"jql": jql, "fields": "comment,project,customfield_24604", "maxResults": 500}
    )
    
    if response.status_code != 200:
        print(f"🚫 Ошибка при поиске задач в Jira. Статус: {response.status_code}")
        return []
        
    issues = response.json().get("issues", [])
    print(f"Найдено задач, обновленных за сутки: {len(issues)}\n")
    
    recent_comments = []
    cutoff_time = datetime.now() - timedelta(days=1)

    for issue in issues:
        issue_key = issue["key"]
        issue_id = issue["id"] 
        project_key = issue.get("fields", {}).get("project", {}).get("key", "")
        
        product_field = issue.get("fields", {}).get("customfield_24604")
        product_name = ""
        
        if isinstance(product_field, dict): 
            product_name = product_field.get("value", product_field.get("name", ""))
        elif isinstance(product_field, list) and product_field:
            val = product_field[0]
            if isinstance(val, dict):
                product_name = val.get("value", val.get("name", ""))
            else:
                product_name = str(val)
        elif isinstance(product_field, str): 
            product_name = product_field
            
        comments = issue.get("fields", {}).get("comment", {}).get("comments", [])
        
        for comment in comments:
            author_name = comment["author"].get("name")
            author_key = comment["author"].get("key") 
            
            if not author_name: 
                author_name = author_key or "Unknown"
            if not author_key: 
                author_key = author_name
                
            created_str = comment["created"][:19] 
            created_time = datetime.strptime(created_str, "%Y-%m-%dT%H:%M:%S")
            comment_id = comment.get("id") 
            
            if created_time > cutoff_time and is_valid_author(author_name, created_time, team_users):
                print(f"[LOG] Найдена цель: {author_name} оставил комментарий (CID:{comment_id}) в {issue_key}")
                recent_comments.append({
                    "comment_id": comment_id,
                    "issue_key": issue_key,
                    "issue_id": issue_id,
                    "project_key": project_key,
                    "product_name": product_name,
                    "author_name": author_name, 
                    "author_key": author_key,   
                    "body": comment["body"],
                    "created": created_time
                })
                
    return recent_comments

def filter_and_group_comments(comments):
    """Отфильтровывает уже обработанные комментарии и склеивает оставшиеся."""
    issue_worklogs = {}
    
    # Загружаем базу существующих ворклогов для проверки
    for c in comments:
        issue_key = c['issue_key']
        if issue_key not in issue_worklogs:
            url = f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}/worklog"
            resp = requests.get(url, headers=JIRA_HEADERS)
            if resp.status_code == 200:
                issue_worklogs[issue_key] = resp.json().get("worklogs", [])
            else:
                issue_worklogs[issue_key] = []
            
    unprocessed = []
    
    for c in comments:
        comment_id = str(c['comment_id'])
        marker = f"CID:{comment_id}"
        is_processed = False
        date_str = c['created'].strftime("%Y-%m-%d")
        
        for wl in issue_worklogs[c['issue_key']]:
            desc = str(wl.get("comment", ""))
            start_date = wl.get("started", "")[:10]
            
            # Проверка 1: Строго по ID комментария (надежно)
            if marker in desc:
                is_processed = True
                break
                
            # Проверка 2: Обратная совместимость (если ворклог был создан до введения CID)
            if start_date == date_str and AUTO_TAG in desc and "CID:" not in desc:
                if c['body'][:30].strip() in desc:
                    is_processed = True
                    break
                
        if not is_processed:
            # Парсим продукт ПЕРЕД группировкой, чтобы знать, склеивать их или нет
            final_product, final_time, clean_body = process_comment_body(
                c['body'], c.get('product_name'), c.get('project_key')
            )
            c['final_product'] = final_product
            c['final_time'] = final_time
            c['clean_body'] = clean_body
            c['date_str'] = date_str
            unprocessed.append(c)
        else:
            print(f"🤔 Комментарий CID:{comment_id} в {c['issue_key']} уже обработан. Пропускаем.")
            
    grouped = {}
    for c in unprocessed:
        # Уникальный ключ группы. Если продукты разные - комментарии склеены не будут!
        group_key = (c['issue_key'], c['author_key'], c['date_str'], c['final_product'])
        
        if group_key not in grouped:
            grouped[group_key] = {
                'issue_key': c['issue_key'],
                'issue_id': c['issue_id'],
                'project_key': c['project_key'],
                'author_name': c['author_name'],
                'author_key': c['author_key'],
                'created': c['created'],
                'final_product': c['final_product'],
                'total_time': 0,
                'bodies': [],
                'comment_ids': []
            }
        grouped[group_key]['total_time'] += c['final_time']
        grouped[group_key]['bodies'].append(c['clean_body'])
        grouped[group_key]['comment_ids'].append(str(c['comment_id']))
        
    return list(grouped.values())

def create_tempo_worklog(agg_data):
    """Создает ворклог на основе сгруппированных данных."""
    cids_str = ",".join(agg_data['comment_ids'])
    
    # Отдельная защита от дублей для авто-встреч
    if 'MEET-' in cids_str:
        issue_key = agg_data['issue_key']
        resp = requests.get(f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}/worklog", headers=JIRA_HEADERS)
        if resp.status_code == 200:
            for wl in resp.json().get("worklogs", []):
                if cids_str in str(wl.get("comment", "")):
                    print(f"🤔 Ворклог для встречи ({cids_str}) пользователя {agg_data['author_name']} уже существует. Пропускаем.")
                    return "skipped", None

    final_product = agg_data['final_product']
    total_time_spent = agg_data['total_time']
    
    # Формируем тело с границами между разными комментариями
    combined_body = "\n---\n".join(agg_data['bodies'])
    if len(combined_body) > 250:
        combined_body = combined_body[:250] + "..."
        
    # НОВОЕ: Перенесли CID в самый конец, чтобы он не засорял интерфейс
    description = f"{AUTO_TAG} {combined_body}\n\n(CID:{cids_str})"
    started_str = agg_data['created'].strftime("%Y-%m-%dT%H:%M:%S.000")
    
    payload = {
        "originTaskId": agg_data['issue_id'], 
        "worker": agg_data['author_key'], 
        "started": started_str,
        "timeSpentSeconds": total_time_spent,
        "comment": description
    }
    
    account_key = None
    
    if final_product: 
        account_key = PRODUCT_ACCOUNT_MAP.get(final_product) 
        
    # Если аккаунт не найден, а задача в INT — ставим MEETING_ACCOUNT_KEY
    if not account_key and agg_data.get("project_key") == "INT": 
        account_key = MEETING_ACCOUNT_KEY
        
    if account_key:
        payload["attributes"] = {
            "_Проект_": {
                "name": "Проект", 
                "value": account_key
            }
        }

    print(f"\n--- Планируемые изменения (Склеено комментариев: {len(agg_data['comment_ids'])}) ---")
    print(f"Задача: {agg_data['issue_key']} | Аккаунт: {account_key or 'Нет'} | CID: {cids_str}")
    print(f"Пользователь: {agg_data['author_name']} | Суммарное время: {round(total_time_spent/60, 1)} мин")
    print("---------------------------------------------------\n")
    
    if DEBUG_MODE:
        return "success", f"{agg_data['author_name']} -> {agg_data['issue_key']} ({round(total_time_spent/60)}м) [DEBUG]"

    response = requests.post(f"{JIRA_BASE_URL}/rest/tempo-timesheets/4/worklogs", headers=TEMPO_HEADERS, json=payload)
    
    if response.status_code in (200, 201):
        print(f"✅ Ворклог успешно создан!")
        return "success", f"{agg_data['author_name']} -> {agg_data['issue_key']} ({round(total_time_spent/60)}м)"
    else:
        print(f"🚫 Ошибка создания ворклога: {response.text}")
        return "error", None

def send_mattermost_report(mode, success_list, skipped, errors):
    """Отправляет красивый сводный отчет в Mattermost."""
    if not MATTERMOST_WEBHOOK_URL:
        return
        
    if not success_list and skipped == 0 and errors == 0:
        return

    if mode == "meetings":
        title = "📅 **Автоматизация встреч (LIFE-5)**"
    else:
        title = "🔄 **Синхронизация комментариев Jira**"

    lines = [title]
    lines.append(f"✅ **Создано ворклогов:** {len(success_list)}")
    lines.append(f"⏩ **Пропущено (уже есть / лимиты):** {skipped}")
    lines.append(f"🚫 **Ошибок API:** {errors}")

    if success_list: 
        lines.append("\n**Детализация списаний:**")
        for item in success_list:
            lines.append(f"• {item}")
        
    payload = {"text": "\n".join(lines)}
    
    if MATTERMOST_DEFAULT_CHANNEL: 
        payload["channel"] = MATTERMOST_DEFAULT_CHANNEL
        
    if MATTERMOST_USERNAME: 
        payload["username"] = MATTERMOST_USERNAME
        
    try: 
        requests.post(MATTERMOST_WEBHOOK_URL, json=payload, timeout=10)
    except Exception as e: 
        print(f"🚫 Ошибка Mattermost: {e}")

def check_user_daily_hours(worker_key, date_str):
    """Считает общую сумму залогированных часов за день."""
    url = f"{JIRA_BASE_URL}/rest/tempo-timesheets/4/worklogs?username={worker_key}&dateFrom={date_str}&dateTo={date_str}"
    response = requests.get(url, headers=TEMPO_HEADERS)
    total_seconds = 0
    if response.status_code == 200:
        for wl in response.json():
            total_seconds += wl.get("timeSpentSeconds", 0)
    return total_seconds

def process_daily_meetings():
    print("\n--- ЗАПУСК АВТОМАТИЗАЦИИ ЕЖЕДНЕВНЫХ ВСТРЕЧ ---")
    
    meeting_issue_id = "UNKNOWN"
    res = requests.get(f"{JIRA_BASE_URL}/rest/api/2/issue/{MEETING_ISSUE_KEY}?fields=id", headers=JIRA_HEADERS)
    if res.status_code == 200: 
        meeting_issue_id = res.json().get("id")
    else: 
        print("🚫 Ошибка: не удалось получить ID задачи для встреч.")
        return 

    today_str = datetime.now().strftime("%Y-%m-%d")
    is_monday = datetime.now().weekday() == 0
    
    team_users = get_team_members()
    active_users = set(TARGET_USERS)
    
    for user, intervals in team_users.items():
        active_users.add(user)
        
    stats = {"success": [], "skipped": 0, "errors": 0}
        
    for user in active_users:
        if user in EXCLUDED_USERS:
            stats["skipped"] += 1
            continue
            
        if is_monday:
            if user in MONDAY_EXCLUDE_USERS:
                stats["skipped"] += 1
                continue
                
            total_hours_today = check_user_daily_hours(user, today_str)
            if total_hours_today >= 28800:
                stats["skipped"] += 1
                continue

        # Создаем фейковые сгруппированные данные для совместимости с новой функцией
        fake_agg_data = {
            'comment_ids': [f"MEET-{today_str}"], 
            'issue_key': MEETING_ISSUE_KEY,
            'issue_id': meeting_issue_id, 
            'project_key': 'LIFE',
            'author_key': user,
            'author_name': user,
            'created': datetime.now(),
            'final_product': MEETING_ACCOUNT_KEY,
            'total_time': 1800, # 30 минут
            'bodies': ["Встреча внутренняя"]
        }
        
        status, msg = create_tempo_worklog(fake_agg_data)
        
        if status == "success": 
            stats["success"].append(msg)
        elif status == "skipped": 
            stats["skipped"] += 1
        elif status == "error": 
            stats["errors"] += 1

    send_mattermost_report("meetings", stats["success"], stats["skipped"], stats["errors"])

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--meetings":
        process_daily_meetings()
    else:
        print(f"\nЗапуск проверки комментариев... (DEBUG_MODE: {DEBUG_MODE})")
        
        team_users = get_team_members()
        comments = get_recent_jira_comments(team_users)
        
        if not comments: 
            print("\nНовых комментариев не найдено.")
            return 
        
        # Запускаем фильтрацию и склейку
        aggregated_tasks = filter_and_group_comments(comments)
        
        if not aggregated_tasks:
            print("Все найденные комментарии уже обработаны ранее.")
            return 
            
        print(f"\nК созданию подготовлено ворклогов (после склейки): {len(aggregated_tasks)}. Начинаем обработку...")
        
        stats = {"success": [], "skipped": 0, "errors": 0}
        
        for agg_data in aggregated_tasks:
            status, msg = create_tempo_worklog(agg_data)
            
            if status == "success": 
                stats["success"].append(msg)
            elif status == "skipped": 
                stats["skipped"] += 1
            elif status == "error": 
                stats["errors"] += 1
                
        send_mattermost_report("comments", stats["success"], stats["skipped"], stats["errors"])

if __name__ == "__main__":
    main()
