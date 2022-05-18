FROM python:3.8-slim-bullseye
LABEL maintainer="Minims"
ENV LANG C.UTF-8

STOPSIGNAL SIGINT

# SomfyProtect2MQTT version
ARG VERSION=0.1.7

ADD . /app
WORKDIR /app

# Install python requirements
RUN pip3 install -r requirements.txt

# Run
ENTRYPOINT ["python3", "./main.py", "-c", "/config/config.yaml"]