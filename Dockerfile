FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Roda como usuario sem privilegios -- se algum dia surgir uma falha que
# permita executar codigo dentro do container, ela nao herda root de
# graca.
RUN useradd --create-home --shell /usr/sbin/nologin solver \
    && chown -R solver:solver /app
USER solver

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
