# Standard Python Image (Bina kisi mise ke)
FROM python:3.11-slim

# Working directory set karein
WORKDIR /app

# Requirements file copy aur install karein
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Saari files copy karein
COPY . .

# Bot start command
CMD ["python", "bot.py"]
