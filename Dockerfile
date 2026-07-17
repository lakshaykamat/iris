FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# data/ is mounted as a volume at runtime; create the dir so SQLite has a home
# on the first run before the volume is attached.
RUN mkdir -p data

CMD ["python", "bot.py"]
