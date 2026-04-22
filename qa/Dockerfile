FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_CONFIG_FILE=/dev/null \
    PIP_INDEX_URL=https://pypi.org/simple

WORKDIR /workspace

COPY qa/requirements.txt /tmp/qa-requirements.txt
RUN python3 -m pip install --no-cache-dir -r /tmp/qa-requirements.txt

COPY qa /workspace/qa

CMD ["python3", "qa/run_scene_suite.py", "--help"]
