FROM python:3.11-alpine

# Устанавливаем рабочую директорию
WORKDIR /app

# Устанавливаем пакет для работы с часовыми поясами
RUN apk add --no-cache tzdata

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем скрипты
COPY comment.py .
COPY entrypoint.sh .

# Делаем скрипт запуска исполняемым
RUN chmod +x entrypoint.sh

# Создаем файл логов
RUN touch /var/log/cron.log

# Указываем скрипт, который будет выполняться при старте контейнера
CMD ["/app/entrypoint.sh"]