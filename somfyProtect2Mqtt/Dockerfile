FROM python:3.12-slim

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

# Install packages requirements
ARG DEBIAN_FRONTEND="noninteractive"

RUN mkdir -p /usr/src/app
WORKDIR /usr/src/app

# Install pip requirements
RUN bash -c "python <(curl -sL https://install.python-poetry.org)"
COPY poetry.lock /usr/src/app
COPY pyproject.toml /usr/src/app
COPY . /usr/src/app


RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
    build-essential libjxl-tools zlib1g-dev libjpeg62-turbo-dev cmake libgl1 libgl1-mesa-glx libglib2.0-0 \
    && python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r requirements/docker.txt \
    && apt-get autoremove --yes build-essential zlib1g-dev libjpeg62-turbo-dev cmake \
    && rm -rf /var/lib/apt/lists/*


RUN ~/.local/bin/poetry install --only main

# Creates a non-root user with an explicit UID and adds permission to access the /app folder
# For more info, please refer to https://aka.ms/vscode-docker-python-configure-containers
RUN adduser -u 5678 --disabled-password --gecos "" appuser && chown -R appuser /usr/src/app
USER appuser

# During debugging, this entry point will be overridden. For more information, please refer to https://aka.ms/vscode-docker-python-debug
ENTRYPOINT ["python", "main.py", "-c", "/config/config.yaml"]
