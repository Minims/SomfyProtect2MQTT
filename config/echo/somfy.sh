#!/bin/bash

RTMPS=`cat /config/somfyprotect2mqtt/stream_url_$1`
echo "ffmpeg:$RTMPS"