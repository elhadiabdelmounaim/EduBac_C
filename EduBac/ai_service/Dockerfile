# Image du service IA. Contexte de construction : le dossier EduBac/ (pour edubac_math).
FROM python:3.12-slim
WORKDIR /srv
COPY ai_service/requirements.txt ai_service/requirements.txt
RUN pip install --no-cache-dir -r ai_service/requirements.txt
COPY edubac_math edubac_math
COPY ai_service ai_service
USER nobody
EXPOSE 8100
CMD ["uvicorn", "ai_service.app:app", "--host", "0.0.0.0", "--port", "8100", "--workers", "2"]
