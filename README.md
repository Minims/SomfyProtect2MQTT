# SomfyProtect2MQTT

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/minims)

Somfy Protect to MQTT

Supported :

- Somfy Home Alarm
- Somfy Home Alarm Advanced
- Somfy One
- Somfy One+

## What is Working

Quite Everything except Video Streaming.

- Retreive some status of the alarm and his devices.
- Set security level: armed, disarmed, partial.
- HA MQTT Discovery.
- Stop the Alarm
- Trigger the Alarm
- Update Device Settings
- Send Action to device (Open/Close Camera Shutter, Light On/Off connected to OutDoor Camera)
- Get lastest Camera snapshot
- Retrieve Smoke Detector status
- Get The temperature from PIR / Siren
- Configure Sensors
- Video Streaming
- ...

<img width="1012" alt="SomfyProtect" src="https://user-images.githubusercontent.com/1724785/112769160-e37df200-901f-11eb-9000-e8c463a64dd9.png">

## Installation

### Requirements

- Use a somfy dedicated user for homeassistant.
- This dedicated user must be declared as a owner, not a child.
- HA MQTT integration must be reconfigure with MQTT Discovery.
- In the config file, check that you have set the name of your house. (The one define in the Somfy App.)

```
sites:
  - Maison
```

### Easy Mode (via HomeAssistant Supervisor)

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FMinims%2Fhomeassistant-addons)

In HomeAssistant, go to Supervisor > Add-on Store > Repositories
Add this repo: https://github.com/minims/homeassistant-addons/

Configure it with you credentials
Then all Devices will appaears in MQTT integration

### Easy Mode (Running in Docker Container)

Add docker container `docker run -v <PATH-TO-CONFIG-FOLDER>:/config minims/somfyprotect2mqtt`

Add config to `<PATH-TO-CONFIG-FOLDER>`

### Manual Mode

Clone the repo
Go to dev branch

```
cd /opt/
git clone https://github.com/Minims/SomfyProtect2MQTT.git
git checkout dev # if you want the dev branch
cd /opt/SomfyProtect2MQTT/
```

Install Python3 dependencies

```
pip3 install -r  somfyProtect2Mqtt/requirements.txt
```

Copy config file and setup your own credentials for SomfyProtect & MQTT.

```
cd /opt/SomfyProtect2MQTT/somfyProtect2Mqtt
cp config/config.yaml.example config/config.yaml
```

## Running

```
cd SomfyProtect2MQTT/somfyProtect2Mqtt
python3 main.py
```

## Video Streaming

1. MQTT Camera
   Currently, Somfy does not provide a permanent streaming URL.
   This is a On-Demand stream, and the stream is live for about 120s.

To start the stream you need:

- To open the cover via the entity `switch.***_shutter_state` in the Camera Device.
- To switch the stream ON via the entity `switch.***_stream` in the Camera Device.

Here is a basic lovelace card to see your camera with bother shutter & stream button

```
camera_view: auto
type: picture-glance
entities:
  - entity: switch.indoor_camera_shutter_state
    icon: mdi:window-shutter-settings
  - entity: switch.indoor_camera_stream
    icon: mdi:play-pause
camera_image: camera.indoor_camera_snapshot
title: Indoor Camera
```

2. go2rtc / WebRTC Camera

Copy file homeassistant/echo/somfy.sh in HA in `/homeassistant/echo/somfy.sh`

- Install HA Addon go2rtc: https://github.com/AlexxIT/go2rtc
- Install HACS WebRTC Camera: https://github.com/AlexxIT/WebRTC

Configure go2rtc:

```
streams:
  somfy_indoor_camera_echo:
    - echo:/homeassistant/echo/somfy.sh <camera device_id>
```

Add WebRTC Camera Card

```
type: custom:webrtc-camera
url: somfy_indoor_camera_echo
shortcuts:
  services:
    - name: Cover
      icon: mdi:window-shutter
      service: switch.toggle
      service_data:
        entity_id: switch.indoor_camera_shutter_state
    - name: Stream
      icon: mdi:play-pause
      service: switch.toggle
      service_data:
        entity_id: switch.indoor_camera_stream
style: >-
  .shortcuts {left: 450px; top: 25px; right: unset; display: flex;
  flex-direction: column; gap: 10px}
```

## Systemd (Running in background on boot)

## 5. (Optional) Running as a daemon with systemctl

To run SomfyProtect2MQTT as daemon (in background) and start it automatically on boot we will run SomfyProtect2MQTT with systemctl.

```bash
# Create a systemctl configuration file for SomfyProtect2MQTT
sudo nano /etc/systemd/system/somfyProtect2mqtt.service
```

Add the following to this file:

```
[Unit]
Description=somfyProtect2mqtt
After=network.target

[Service]
WorkingDirectory=/opt/SomfyProtect2MQTT/somfyProtect2Mqtt
ExecStart=/usr/bin/python3 /opt/SomfyProtect2MQTT/somfyProtect2Mqtt/main.py
StandardOutput=inherit
# Or use StandardOutput=null if you don't want SomfyProtect2MQTT messages filling syslog, for more options see systemd.exec(5)
StandardError=inherit
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

Save the file and exit.

Verify that the configuration works:

```bash
# Start SomfyProtect2MQTT
sudo systemctl start somfyProtect2mqtt

# Show status
systemctl status somfyProtect2mqtt.service
```

Now that everything works, we want systemctl to start SomfyProtect2MQTT automatically on boot, this can be done by executing:

```bash
sudo systemctl enable somfyProtect2mqtt.service
```

Done! 😃

Some tips that can be handy later:

```bash
# Stopping SomfyProtect2MQTT
sudo systemctl stop somfyProtect2mqtt

# Starting SomfyProtect2MQTT
sudo systemctl start somfyProtect2mqtt

# View the log of SomfyProtect2MQTT
sudo journalctl -u somfyProtect2mqtt.service -f
```

## Developement

This code is base on reverse engineering of the Android Mobile App.

- https://apkgk.com/APK-Downloader?package=com.myfox.android.mss
- Decompilation : https://github.com/google/enjarify

```
python3 -O -m enjarify.main ../com-myfox-android-mss1610600400.apk
ls
com-myfox-android-mss1610600400-enjarify.jar
```

- Open JAR and Get Java Code (JD-UI) : https://github.com/java-decompiler/jd-gui/releases

So if you want to contribue, have knowledge in JAVA / APK, you can help to find all API calls used in the APP.
We can integrate here (https://github.com/Minims/somfy-protect-api) to use it.

- Use APKTool to get smali files and all available API Endpoints
