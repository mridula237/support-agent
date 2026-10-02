FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python crm_server/seed_db.py

EXPOSE 8000

CMD ["python", "run.py"]