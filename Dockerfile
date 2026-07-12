FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY . .
RUN pip install --no-cache-dir .
RUN mkdir -p storage/images storage/reports
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
