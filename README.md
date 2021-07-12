# SomfyProtect2MQTT
Somfy Protect to MQTT

## What is Working
This an alpha dev version

 - Retreive some status of the alarm and his devices.
 - Set security level: armed, disarmed, partial.
 - HA MQTT Discovery.
 - Stop the Alarm
 - Trigger the Alarm
 - Update Device Settings
 - Send Action to device (Open/Close Camera Shutter)
 - Get lastest Camera snapshot
 - Retrieve Smoke Detector status

Ex:

<img width="1012" alt="SomfyProtect" src="https://user-images.githubusercontent.com/1724785/112769160-e37df200-901f-11eb-9000-e8c463a64dd9.png">

## TODO

 - Test all things (/)
 - Validate Somfy OutDoor Camera (/)
 - Try to retreive Camera Stream
 - TBD

## Installation

### Easy Mode (via HomeAssistant Supervisor)

In HomeAssistant, go to Supervisor > Add-on Store > Repositories
Add this repo from @schumijo: https://github.com/schumijo/homeassistant-addons/
Thx to him for his work.
Configure it with you credentials
Then all Devices will appaears in MQTT integration

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
 * https://apkgk.com/APK-Downloader?package=com.myfox.android.mss
 * Decompilation : https://github.com/google/enjarify

 ```
 python3 -O -m enjarify.main ../com-myfox-android-mss1610600400.apk
 ls
 com-myfox-android-mss1610600400-enjarify.jar
 ```

 * Open JAR and Get Java Code (JD-UI) : https://github.com/java-decompiler/jd-gui/releases

 So if you want to contribue, have knowledge in JAVA / APK, you can help to find all API calls used in the APP.
 We can integrate here (https://github.com/Minims/somfy-protect-api) to use it.

 * Use APKTool to get smali files and all available API Endpoints
