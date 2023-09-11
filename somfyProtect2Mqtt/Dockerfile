# For more information, please refer to https://aka.ms/vscode-docker-python
FROM python:3.11-slim

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

# Install packages requirements
ARG DEBIAN_FRONTEND="noninteractive"

# Install pip requirements
COPY requirements.txt .

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
    python3-opencv ffmpeg \
    && python -m pip install -r requirements_addons.txt \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# Creates a non-root user with an explicit UID and adds permission to access the /app folder
# For more info, please refer to https://aka.ms/vscode-docker-python-configure-containers
RUN adduser -u 5678 --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

# During debugging, this entry point will be overridden. For more information, please refer to https://aka.ms/vscode-docker-python-debug
ENTRYPOINT ["python", "main.py", "-c", "/config/config.yaml"]
