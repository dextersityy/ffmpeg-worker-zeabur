# Menggunakan image Python yang ringan
FROM python:3.8-slim-buster

# Memperbarui list paket dan menginstal FFmpeg serta yt-dlp
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsm6 libxext6 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Instal Flask dan yt-dlp di lingkungan Python
RUN pip install Flask yt-dlp

# Mengatur direktori kerja
RUN mkdir -p /data/clips && chmod -R 777 /data/clips
WORKDIR /app

# Menyalin kode API kita ke dalam container
COPY app.py .

# Menyalin file konfigurasi lain
COPY requirements.txt .
RUN pip install -r requirements.txt

# Mendefinisikan port yang akan di-expose (default Zeabur biasanya 8080)
EXPOSE 8080

# Perintah untuk menjalankan server Flask saat container dimulai
CMD ["python", "app.py"]
