# SomfyProtect2MQTT

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/minims)
[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/minims)

Somfy Protect to MQTT

Supported:

- Somfy Home Alarm
- Somfy Home Alarm Advanced
- Somfy One
- Somfy One+

## What is Working

- Retrieve some status of the alarm and its devices.
- Set security level: armed, disarmed, partial (HA aliases `armed_away` and `armed_night` are also supported on MQTT command payloads).
- HA MQTT Discovery.
- Stop the Alarm
- Trigger the Alarm
- Update Device Settings
- Send Action to device (Open/Close Camera Shutter, Light On/Off connected to OutDoor Camera)
- Get latest Camera snapshot
- Retrieve Smoke Detector status
- Get The temperature from PIR / Siren
- Configure Sensors
- Video Streaming <alpha>

<img width="1012" alt="SomfyProtect" src="https://user-images.githubusercontent.com/1724785/112769160-e37df200-901f-11eb-9000-e8c463a64dd9.png">

## Installation

### Requirements

- Use a Somfy dedicated user for Home Assistant.
- This dedicated user must be declared as an owner, not a child user.
- HA MQTT integration must be reconfigured with MQTT Discovery.
- In the config file, check that you have set the name of your house. (The one defined in the Somfy App.)

```
sites:
  - Maison
```

### Easy Mode (via HomeAssistant Supervisor)

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FMinims%2Fhomeassistant-addons)

In HomeAssistant, go to Supervisor > Add-on Store > Repositories
Add this repo: https://github.com/minims/homeassistant-addons/

Configure it with your credentials
Then all devices will appear in MQTT integration

### Easy Mode (Running in Docker Container)

Run docker container (recommended: pin a version tag):

`docker run -v <PATH-TO-CONFIG-FOLDER>:/config minims/somfyprotect2mqtt:<VERSION>`

Example:

`docker run -v <PATH-TO-CONFIG-FOLDER>:/config minims/somfyprotect2mqtt:v2026.2.0`

Add config to `<PATH-TO-CONFIG-FOLDER>`

OAuth tokens are cached in `<PATH-TO-CONFIG-FOLDER>/token.json` with restricted file permissions.
The config folder must be writable and persistent; read-only mounts such as Kubernetes Secrets will prevent token
caching and trigger Somfy token rate limits after repeated starts.
Legacy `token.json` files from older versions are migrated automatically on startup when possible.

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
pip3 install -r somfyProtect2Mqtt/requirements/common.txt
```

Copy config file and setup your own credentials for SomfyProtect & MQTT.

```
cd /opt/SomfyProtect2MQTT/somfyProtect2Mqtt
cp config/config.yaml.example config/config.yaml
```

The OAuth token cache is stored next to the config file as `config/token.json` and contains local secret material.
The config directory must be writable and persistent so the token can be reused across restarts.

### Link Somfy badges to Bluetooth devices

The Somfy API does not expose the Bluetooth address of key fobs. To let Home Assistant associate a badge discovered
as `Myfox R` with its MQTT device, add the address shown as `Address` in Home Assistant to `homeassistant_config`.
Use the Somfy device ID when possible; a unique device label is also accepted:

```yaml
homeassistant_config:
  device_macs:
    "<Somfy badge device ID or unique label>": "AA:BB:CC:DD:EE:FF"
```

The `Source` shown in the Bluetooth advertisement is the scanner or Bluetooth proxy, not the badge. Restart
SomfyProtect2MQTT after updating the configuration so it republishes MQTT discovery.

## Running

```
cd /opt/SomfyProtect2MQTT/somfyProtect2Mqtt
python3 main.py -c config/config.yaml
```

## Video Streaming

Somfy does not provide a permanent streaming URL. Streams are started on demand
and usually stay live for about 120 seconds.

To start a stream:

- Open the camera shutter with `switch.***_shutter_state`.
- Start the stream with `switch.***_stream`.
- Select the video backend exposed by Home Assistant/MQTT: `evostream` or `webrtc`.

### MQTT Camera

Basic Lovelace card with shutter and stream controls:

```yaml
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

### go2rtc / WebRTC Camera

Install:

- HA Add-on go2rtc: https://github.com/AlexxIT/go2rtc
- HACS WebRTC Camera: https://github.com/AlexxIT/WebRTC

The go2rtc source depends on the selected Somfy video backend.

#### Backend `evostream`

Use the echo script. It reads the RTMPS URL written by SomfyProtect2MQTT when
the stream starts.

Copy `config/echo/somfy.sh` to Home Assistant as `/config/echo/somfy.sh`, then
configure go2rtc:

```yaml
streams:
  somfy_indoor_camera:
    - echo:/config/echo/somfy.sh <camera device_id>
```

#### Backend `webrtc`

Do not use the echo script. SomfyProtect2MQTT exposes the WebRTC stream as an
HLS playlist on port `8090`.

Use `stream_start` to start the camera stream. `stream_stop` is only supported
by the Somfy `evostream` backend and is ignored when the camera uses `webrtc`.

Where that server listens is configurable, and defaults to every interface:

```yaml
hls_host: 0.0.0.0
hls_port: 8090
```

The playlist is unauthenticated, so an installation whose reader runs on the
same host as SomfyProtect2MQTT can set `hls_host` to `127.0.0.1` and keep the
camera off the local network. `hls_port` is there because `8090` is not this
project's alone — `motion`, for one, hands it to its first camera.

Configure go2rtc with the HLS URL:

```yaml
streams:
  somfy_indoor_camera:
    - http://<somfyprotect2mqtt_host>:8090/<camera device_id>/playlist.m3u8
```

If go2rtc runs in the same network namespace as SomfyProtect2MQTT, the URL can
be:

```yaml
streams:
  somfy_indoor_camera:
    - http://0.0.0.0:8090/<camera device_id>/playlist.m3u8
```

Add WebRTC Camera card:

```yaml
type: custom:webrtc-camera
url: somfy_indoor_camera
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

## Running as a daemon with systemctl

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
ExecStart=/usr/bin/python3 /opt/SomfyProtect2MQTT/somfyProtect2Mqtt/main.py -c /opt/SomfyProtect2MQTT/somfyProtect2Mqtt/config/config.yaml
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

## Development

This code is based on reverse engineering of the Android Mobile App.

- https://apkgk.com/APK-Downloader?package=com.myfox.android.mss
- Decompilation : https://github.com/google/enjarify

```
python3 -O -m enjarify.main ../com-myfox-android-mss1610600400.apk
ls
com-myfox-android-mss1610600400-enjarify.jar
```

- Open JAR and Get Java Code (JD-UI) : https://github.com/java-decompiler/jd-gui/releases

So if you want to contribute, have knowledge in JAVA / APK, you can help to find all API calls used in the APP.
We can integrate here (https://github.com/Minims/somfy-protect-api) to use it.

- Use APKTool to get smali files and all available API Endpoints
