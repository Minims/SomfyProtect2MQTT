# SomfyProtect2MQTT
Somfy Protect to MQTT

## What is Working
This an alpha dev version

 - Retreive some status of the alarm and his devices.
 - Set security level: armed, disarmed, partial.
 - HA MQTT Discovery.

Ex:

<img width="1012" alt="SomfyProtect" src="https://user-images.githubusercontent.com/1724785/112769160-e37df200-901f-11eb-9000-e8c463a64dd9.png">

## TODO

 - Control Indoor Camera roller_sutter
 - Fix status when alarm is triggered

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

