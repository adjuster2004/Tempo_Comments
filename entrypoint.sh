#!/bin/sh

# Очищаем старые задачи
> /etc/crontabs/root

# Ищем переменные для синхронизации комментариев (SYNC_CRON)
env | grep -E 'SYNC_CRON[0-9]*=' | while IFS='=' read -r name value; do
    # Убираем возможные кавычки из значения, если они есть
    clean_value=$(echo "$value" | tr -d '"' | tr -d "'")
    echo "$clean_value cd /app && python /app/comment.py >> /var/log/cron.log 2>&1" >> /etc/crontabs/root
done

# Ищем переменную для автоматизации встреч (MEETING_CRON)
env | grep -E 'MEETING_CRON=' | while IFS='=' read -r name value; do
    # Убираем возможные кавычки из значения, если они есть
    clean_value=$(echo "$value" | tr -d '"' | tr -d "'")
    echo "$clean_value cd /app && python /app/comment.py --meetings >> /var/log/cron.log 2>&1" >> /etc/crontabs/root
done

# Если ничего не нашли - ставим дефолтный запуск каждый час
if [ ! -s /etc/crontabs/root ]; then
    echo "0 * * * * cd /app && python /app/comment.py >> /var/log/cron.log 2>&1" > /etc/crontabs/root
    echo "⚠️ Переменные SYNC_CRON или MEETING_CRON не найдены в .env! Установлен запуск по умолчанию (раз в час)."
fi

echo "Текущее время в контейнере: $(date)"
echo "--- Расписание CRON ---"
cat /etc/crontabs/root
echo "-----------------------"

# Запускаем cron в фоне и слушаем логи
crond -l 2 -b
tail -f /var/log/cron.log