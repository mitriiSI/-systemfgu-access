FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng antiword libseccomp2 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN --mount=type=secret,id=system_ca if [ -s /run/secrets/system_ca ]; then export PIP_CERT=/run/secrets/system_ca; fi; pip install --no-cache-dir --upgrade 'pip>=26.2.1' 'setuptools>=83.0.0' && pip install --no-cache-dir -r requirements.txt
ENV PYTHONDONTWRITEBYTECODE=1
COPY . .
RUN chmod 700 /app
EXPOSE 5000
CMD ["python", "run.py"]
