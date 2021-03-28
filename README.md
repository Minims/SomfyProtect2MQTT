# SomfyProtect2MQTT
Somfy Protect to MQTT

## What is Working
This an alpha dev version

 - Only retreive some status of the alarm and his devices.
 - No Action for now.
 - HA MQTT Discovery.

Ex: 

<img width="1012" alt="SomfyProtect" src="https://user-images.githubusercontent.com/1724785/112769160-e37df200-901f-11eb-9000-e8c463a64dd9.png">


## Installation

Clone the repo
Go to dev branch

```
git checkout dev
```

Install Python3 dependencies

```
pip3 install -r  somfyProtect2Mqtt/requirements.txt
```

Copy config file and setup your own credentials for SomfyProtect & MQTT.

```
cp config/config.yaml.example config/config.yaml
```

## Running

```
cd SomfyProtect2MQTT/somfyProtect2Mqtt
python3 main.py
```
