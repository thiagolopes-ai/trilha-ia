FROM python:3.11-slim

# Usuário sem privilégio. Container que roda como root é achado de auditoria
# em qualquer revisão de segurança séria.
RUN useradd --create-home --uid 10001 trilha

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY trilha/ ./trilha/
COPY api.py avaliar.py preparar_casos.py conferir_gabarito.py ./
COPY dados/casos.json ./dados/

# O banco fica em volume: a trilha precisa sobreviver ao container.
RUN mkdir -p /dados && chown trilha:trilha /dados
VOLUME ["/dados"]
ENV TRILHA_BANCO=/dados/trilha.db

USER trilha
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/saude')"

# TRILHA_CHAVE não tem valor padrão de propósito: sem chave o serviço não sobe.
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
