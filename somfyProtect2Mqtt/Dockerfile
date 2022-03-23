FROM python:3.8-slim-bullseye
LABEL maintainer="Minims"
ENV LANG C.UTF-8

STOPSIGNAL SIGINT

# SomfyProtect2MQTT version
ARG VERSION=0.1.7

# Download source and untar
WORKDIR /usr/src
ADD "https://github.com/Minims/SomfyProtect2MQTT/archive/refs/heads/dev.tar.gz" src.tar.gz
RUN tar -xvf src.tar.gz
RUN mv /usr/src/SomfyProtect2MQTT-dev /usr/src/SomfyProtect2MQTT

# Install python requirements
WORKDIR /usr/src/SomfyProtect2MQTT/somfyProtect2Mqtt
RUN pip3 install -r requirements.txt

# Run
ENTRYPOINT ["./docker-entrypoint.sh"]