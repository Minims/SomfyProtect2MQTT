FROM python:3.8-slim-buster
ENV LANG C.UTF-8

# SomfyProtect2MQTT version
ARG VERSION=0.1.3

# Install required packages
RUN apk add --no-cache py3-pip

# Download source and untar
WORKDIR /usr/src
ADD "https://github.com/Minims/SomfyProtect2MQTT/archive/refs/heads/dev.tar.gz" src.tar.gz
RUN tar -xvf src.tar.gz
RUN mv /usr/src/SomfyProtect2MQTT-dev /usr/src/SomfyProtect2MQTT

# Install python requirements
WORKDIR /usr/src/SomfyProtect2MQTT/somfyProtect2Mqtt
RUN pip3 install -r requirements.txt

COPY config/config.yaml /usr/src/SomfyProtect2MQTT/somfyProtect2Mqtt/config/config.yaml

# Run script
CMD [ "python3" "/usr/src/SomfyProtect2MQTT/somfyProtect2Mqtt/main.py" "-v" ]
