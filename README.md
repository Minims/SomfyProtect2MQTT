# SomfyProtect2MQTT

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/minims)
[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/minims)

Bridge between **Somfy Protect** alarm systems and **MQTT**, enabling seamless integration with **Home Assistant** and other home automation platforms.

## Table of Contents

- [Supported Systems](#supported-systems)
- [Supported Devices](#supported-devices)
- [Features](#features)
- [Installation](#installation)
- [Configuration](#configuration)
- [Configuration Reference](#configuration-reference)
- [Video Streaming](#video-streaming)
- [Running as a Daemon](#running-as-a-daemon-with-systemctl)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [Development](#development)

## Supported Systems

| System | Status |
|--------|--------|
| Somfy Home Alarm | Fully Supported |
| Somfy Home Alarm Advanced | Fully Supported |
| Somfy One | Fully Supported |
| Somfy One+ | Fully Supported |

## Supported Devices

| Device | Status | Control | Snapshot | Streaming | Temperature |
|--------|--------|---------|----------|-----------|-------------|
| **Cameras** |
| Indoor Camera | Supported | Shutter, Reboot | Yes | Yes (alpha) | - |
| Outdoor Camera | Supported | Shutter, Light, Reboot | Yes | Yes (alpha) | - |
| Myfox Security Camera | Supported | Shutter, Reboot | Yes | Yes (alpha) | - |
| Somfy One | Supported | Shutter, Reboot | Yes | Yes (alpha) | - |
| Somfy One+ | Supported | Shutter, Reboot | Yes | Yes (alpha) | - |
| **Sensors** |
| IntelliTag | Supported | Configure | - | - | Yes |
| Infrared Sensor (PIR) | Supported | Configure | - | - | Yes |
| Smoke Detector | Supported | Test | - | - | - |
| **Sirens** |
| Indoor Siren | Supported | Test sounds | - | - | Yes |
| Outdoor Siren | Supported | Test sounds | - | - | Yes |
| **Other** |
| Key Fob | Supported | Presence | - | - | - |
| Link (Hub) | Supported | Reboot, Halt | - | - | - |
| Extender | Supported | - | - | - | - |
| Door Lock | Supported | Lock/Unlock | - | - | - |
| Door Lock Gateway | Supported | - | - | - | - |
| Visiophone | Supported | Gate, Latch, Snapshot | Yes | Yes (alpha) | - |

## Features

### Alarm Control
- Set security level: **armed**, **disarmed**, **partial**
- Trigger the alarm (silent or audible)
- Stop the alarm
- Panic mode

### Device Management
- Retrieve status of all devices
- Update device settings
- Configure sensor sensitivity
- Control camera shutter (open/close)
- Control outdoor camera light

### Home Assistant Integration
- Full MQTT Auto-Discovery support
- All devices automatically appear in HA
- Real-time status updates via WebSocket

### Camera Features
- Get latest snapshot
- Video streaming (alpha) via MQTT or go2rtc/WebRTC
- Motion detection events

<img width="1012" alt="SomfyProtect" src="https://user-images.githubusercontent.com/1724785/112769160-e37df200-901f-11eb-9000-e8c463a64dd9.png">

## Installation

### Requirements

- A **dedicated Somfy account** for Home Assistant
  - This user must be declared as an **owner**, not a child user
- **MQTT broker** (e.g., Mosquitto)
- **Home Assistant MQTT integration** configured with MQTT Discovery enabled
- Your **site name** exactly as defined in the Somfy Protect app

### Easy Mode (Home Assistant Add-on)

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FMinims%2Fhomeassistant-addons)

1. In Home Assistant, go to **Settings > Add-ons > Add-on Store**
2. Click the menu (top right) and select **Repositories**
3. Add: `https://github.com/minims/homeassistant-addons/`
4. Install **SomfyProtect2MQTT** add-on
5. Configure with your credentials
6. Start the add-on
7. Devices will appear in the MQTT integration

### Docker

```bash
docker run -d \
  --name somfyprotect2mqtt \
  -v /path/to/config:/config \
  --restart unless-stopped \
  minims/somfyprotect2mqtt
```

Create your `config.yaml` in `/path/to/config/` (see [Configuration](#configuration)).

### Manual Installation

```bash
# Clone the repository
cd /opt/
git clone https://github.com/Minims/SomfyProtect2MQTT.git
cd SomfyProtect2MQTT/

# Install dependencies
pip3 install -r somfyProtect2Mqtt/requirements/common.txt

# Copy and edit configuration
cd somfyProtect2Mqtt
cp config/config.yaml.example config/config.yaml
nano config/config.yaml
```

## Running

```bash
cd /opt/SomfyProtect2MQTT/somfyProtect2Mqtt
python3 main.py -c config/config.yaml
```

Options:
- `-c, --configuration`: Path to config file
- `-v, --verbose`: Enable debug logging

## Configuration

Create a `config.yaml` file with the following structure:

```yaml
somfy_protect:
  username: your_somfy_email@example.com
  password: your_somfy_password
  sites:
    - "Your Home Name"  # Exactly as shown in Somfy Protect app

homeassistant_config:
  code: 1234                    # Optional: Alarm code
  code_arm_required: false      # Require code to arm
  code_disarm_required: true    # Require code to disarm

mqtt:
  host: 192.168.1.10            # MQTT broker IP/hostname
  port: 1883                    # MQTT broker port
  ssl: false                    # Enable SSL/TLS
  username: mqtt_user           # MQTT username
  password: mqtt_password       # MQTT password
  client-id: somfy-protect      # MQTT client ID
  topic_prefix: somfyProtect2mqtt
  ha_discover_prefix: homeassistant

delay_site: 60                  # Site refresh interval (seconds, min: 60)
delay_device: 60                # Device refresh interval (seconds, min: 60)
manual_snapshot: true           # Manual snapshot mode (vs automatic)
streaming: go2rtc               # Streaming mode: mqtt or go2rtc
debug: false                    # Enable debug logging
```

## Configuration Reference

### Somfy Protect Settings

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `username` | string | Yes | Your Somfy Protect account email |
| `password` | string | Yes | Your Somfy Protect account password |
| `sites` | list | Yes | List of site names to monitor (as shown in app) |

### Home Assistant Settings

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `code` | integer | - | Alarm code for arming/disarming |
| `code_arm_required` | boolean | false | Require code to arm the alarm |
| `code_disarm_required` | boolean | true | Require code to disarm the alarm |

### MQTT Settings

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `host` | string | - | MQTT broker hostname or IP |
| `port` | integer | 1883 | MQTT broker port |
| `ssl` | boolean | false | Enable SSL/TLS connection |
| `username` | string | - | MQTT username |
| `password` | string | - | MQTT password |
| `client-id` | string | somfy-protect | MQTT client identifier |
| `topic_prefix` | string | somfyProtect2mqtt | Base topic for all messages |
| `ha_discover_prefix` | string | homeassistant | Home Assistant discovery prefix |

### General Settings

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `delay_site` | integer | 60 | Site status refresh interval in seconds (min: 60) |
| `delay_device` | integer | 60 | Device status refresh interval in seconds (min: 60) |
| `manual_snapshot` | boolean | false | If true, snapshots only on demand |
| `streaming` | string | mqtt | Video streaming mode: `mqtt` or `go2rtc` |
| `debug` | boolean | false | Enable verbose debug logging |

## Video Streaming

Somfy does not provide permanent streaming URLs. Streams are on-demand and live for approximately 120 seconds.

### Option 1: MQTT Camera

To start a stream:
1. Open the camera shutter via `switch.***_shutter_state`
2. Start the stream via `switch.***_stream`

Example Lovelace card:

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

### Option 2: go2rtc / WebRTC (Recommended)

This provides better quality and lower latency.

1. Copy `config/echo/somfy.sh` to `/config/echo/somfy.sh` in Home Assistant
2. Install [go2rtc add-on](https://github.com/AlexxIT/go2rtc)
3. Install [WebRTC Camera](https://github.com/AlexxIT/WebRTC) via HACS

Configure go2rtc:
```yaml
streams:
  somfy_indoor_camera:
    - echo:/config/echo/somfy.sh <camera_device_id>
```

Example WebRTC card:
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
```

## Running as a Daemon with systemctl

```bash
# Create service file
sudo nano /etc/systemd/system/somfyProtect2mqtt.service
```

Add:
```ini
[Unit]
Description=SomfyProtect2MQTT
After=network.target

[Service]
WorkingDirectory=/opt/SomfyProtect2MQTT/somfyProtect2Mqtt
ExecStart=/usr/bin/python3 main.py -c config/config.yaml
StandardOutput=inherit
StandardError=inherit
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable somfyProtect2mqtt
sudo systemctl start somfyProtect2mqtt
```

Useful commands:
```bash
sudo systemctl status somfyProtect2mqtt   # Check status
sudo systemctl restart somfyProtect2mqtt  # Restart
sudo journalctl -u somfyProtect2mqtt -f   # View logs
```

## Troubleshooting

### Authentication Errors

**Problem**: `Token expired` or authentication failures

**Solutions**:
1. Verify your Somfy credentials are correct
2. Ensure the account is an **owner**, not a child user
3. Delete `token.json` and restart to force re-authentication
4. Check if you can log in to the Somfy Protect app

### Devices Not Appearing

**Problem**: Devices don't show up in Home Assistant

**Solutions**:
1. Check your site name matches exactly (case-sensitive) what's in the Somfy app
2. Verify MQTT Discovery is enabled in Home Assistant
3. Check MQTT broker connectivity
4. Look at the logs for error messages:
   ```bash
   python3 main.py -c config/config.yaml --verbose
   ```

### Camera Snapshots Not Working

**Problem**: Camera entity shows but no image

**Solutions**:
1. Ensure the camera shutter is open (`switch.***_shutter_state`)
2. Check if `manual_snapshot: false` for automatic updates
3. Verify camera is online in the Somfy app
4. Try triggering a manual snapshot via the switch

### WebSocket Disconnections

**Problem**: Frequent "Websocket is DEAD" messages

**Solutions**:
1. Check your internet connection stability
2. The application auto-reconnects, but frequent disconnections may indicate network issues
3. Consider using the Home Assistant add-on for better stability

### MQTT Connection Issues

**Problem**: Cannot connect to MQTT broker

**Solutions**:
1. Verify MQTT broker is running: `mosquitto -v`
2. Check firewall rules for port 1883 (or your configured port)
3. Verify credentials if authentication is enabled
4. Test with `mosquitto_pub` and `mosquitto_sub`

## FAQ

**Q: Can I use multiple Somfy sites?**  
A: Yes, add multiple site names to the `sites` list in your configuration.

**Q: Why do I need a dedicated Somfy account?**  
A: Using a dedicated account prevents session conflicts when you use the mobile app simultaneously.

**Q: Is video streaming reliable?**  
A: Video streaming is in alpha. Somfy's on-demand streaming has a 120-second limit, which is a platform limitation.

**Q: How often are device statuses updated?**  
A: By default, every 60 seconds. Real-time updates for events (motion, alarms) are received via WebSocket.

**Q: Can I control the alarm from Home Assistant?**  
A: Yes, you can arm, disarm, trigger, and stop the alarm via the alarm_control_panel entity.

## Development

This project is based on reverse engineering of the Somfy Protect Android app.

### Tools Used
- [APK Downloader](https://apkgk.com/APK-Downloader?package=com.myfox.android.mss)
- [enjarify](https://github.com/google/enjarify) - DEX to JAR converter
- [JD-GUI](https://github.com/java-decompiler/jd-gui/releases) - Java decompiler
- APKTool for smali analysis

### Contributing

Contributions are welcome! If you have knowledge of Java/APK reverse engineering, you can help discover additional API endpoints.

See also: [somfy-protect-api](https://github.com/Minims/somfy-protect-api)

## License

This project is licensed under the GPL-3.0 License.

## Support

- [Report an issue](https://github.com/Minims/SomfyProtect2MQTT/issues)
- [Buy me a coffee](https://www.buymeacoffee.com/minims)
- [Ko-fi](https://ko-fi.com/minims)
