#!/bin/bash

RTMPS=`cat /homeassistant/somfyprotect2mqtt/stream_url_$1`
echo "ffmpeg:$RTMPS"