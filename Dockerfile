FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
# pip al dia antes de instalar (la imagen base trae uno antiguo con avisos de seguridad)
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home appuser
USER appuser

EXPOSE 8080

COPY --chown=appuser:appuser start.sh .
RUN chmod +x start.sh

CMD ["./start.sh"]
