# backend/Dockerfile

# Use a modern, slim Python runtime
FROM python:3.13-slim

# Set the main working directory for the application
WORKDIR /app

# Install system dependencies that might be needed
# (Örn: `psycopg2-binary` için `libpq-dev` gerekebilir)
# RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*

# Copy only the requirements file first to leverage Docker cache
COPY ./backend/requirements.txt .

# Install dependencies, including gunicorn
RUN pip install --no-cache-dir -r requirements.txt

# Copy your application code into the 'backend' sub-directory
COPY ./backend /app/backend

# --- DEĞİŞİKLİK: CMD komutunu Gunicorn kullanacak şekilde güncelliyoruz ---
# Bu, imajın varsayılan başlatma komutu olur.
# docker-compose'daki 'command' direktifi bu satırı ezecektir,
# ancak imajın kendi başına çalıştırılabilirliği için bu iyi bir pratiktir.
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "1", "-b", "0.0.0.0:8000", "backend.main:app"]
