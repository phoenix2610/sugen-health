FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY coder/ coder/
COPY problem/data/mms-2026-01.json problem/data/mms-2026-01.json
# fail the build early if the shipped knowledge base does not load
RUN python -c "from coder.kb import KB; from coder.nokey import Ranker; k=KB(); print(len(k.codes), 'codes,', len(k.terms), 'terms')"

ENTRYPOINT ["python", "-m", "coder"]
