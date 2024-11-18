# zellostream
Python scripts to stream audio one way to a Zello channel.  Designed for Python 3.X

Acquires audio from a sound card or UDP port to send to Zello.  (UDP support is designed for use with trunk-recorder and the [simplestream plugin](https://github.com/robotastic/trunk-recorder/blob/master/docs/CONFIGURE.md#simplestream-plugin)).

Create a developer account with Zello to get credentials.  Set up a different account than what you normally use for Zello, as trying to use this script with the same account that you're using on your mobile device will cause problems.

For Zello consumer network:
- Go to https://developers.zello.com/ and click Login
- Enter your Zello username and password. If you don't have Zello account download Zello app and create one.
- Complete all fields in the developer profile and click Submit
- Click Keys and Add Key
- Copy and save Sample Development Token, Issuer, and Private Key. Make sure you copy each of the values completely using Select All.
- Click Close
- Copy the Private Key into a file called privatekey.pem that's in the same folder as the script.
- The Issuer value goes into config.json.

For Zello Work network:
- The issuer and private key are not needed if zello_work_account_name is defined.

## config.json
- username:  Zello account username to use for streaming
- password:  Zello account password to use for streaming
- zello_channel:  name of the zello channel to stream to
- issuer:  Issuer credential from Zello account (see above)
- vox_silence_time:  Time in seconds of detected silence before streaming stops. Default: 3
- audio_threshold:  Audio detected above this level will be streamed. Default: 1000
- audio_source: Set to "Sound Card" (default) or "UDP"
- input_device_index:  Index of the audio input device to use for streaming when audio_source is set to "Sound Card". Use list_devices.py to find the right index. Default 0
  - Use list_devices_portaudio.py to find the right index.
- output_device_index:  Index of the audio output device to use for streaming from Zello. Default 0
  - Use list_devices_portaudio.py to find the right index.
- zello_sample_rate: Sample rate of the stream sent to Zello (samples per seconds). Default: 16000
- audio_input_sample_rate: Sample rate of the audio device or UDP stream (samples per seconds). Default: 48000 (set to 8000 or use with UDP stream from trunk-recorder)
- audio_input_channels: Number of audio channels in the device. 1 for mono, 2 for stereo. Default 1
- input_pulse_name: Used to re-route input from a Pulseaudio device. This is the name of the device.  Not applicable on Windows.
  - Use list_devices_pulseaudio.py to find the right device name
- in_channel_config: Channel to send. "mono" for mono device. "left", "right" or "mix" for stereo device. Default: mono
- audio_output_sample_rate: Sample rate of the output audio device (samples per seconds). Default: 48000
- audio_output_channels: Number of audio channels in the output device. 1 for mono, 2 for stereo. Default 1
- output_pulse_name: Used to re-route output to a Pulseaudio device. This is the name of the device.  Not applicable on Windows.
  - Use list_devices_pulseaudio.py to find the right device name
- ptt_on_command: Optional command to execute to turn host PTT on when receiving audio from Zello. It is in the form of a list of command followed by its arguments
- ptt_off_command: Optional command to execute to turn host PTT off when audio from Zello has finished. It is in the form of a list of command followed by its arguments
- ptt_off_delay: Delay in seconds applied before sending the PTT off command. Covers possible delay to play the stream entirely. Default 2 seconds.
- logging_level: Set Python logging module to this level. Can be "critial", "error", "warning", "info" or "debug". Default "warning".
- TGID_in_stream: Only used when audio_source is set to "UDP". When true, a four-byte talkgroup ID is expected prior to the audio data in each incoming UDP packet and only the talkgroup specified in TGID_to_play will be streamed.  Default is false.
- TGID_to_play: Only used when audio_source is set to "UDP". When TGID_in_stream is set to true, the integer in this field specifies which talkgroup ID will be streamed. Default 70000
- UDP_PORT: Only used when audio_source is set to "UDP". UDP port to listen for oncompressed PCM audio on.  Audio received on this port will be compressed and streamed to Zello. Default 9123
- zello_work_account_name: Use only when streaming to a ZelloWork account. Include just the zellowork subdomain name here. If you access your zello work account at https://zellostream.zellowork.com, your subdomain would just be zellostream. If left blank, the public zello network will be used.

## Dependencies
### Windows
Requires these DLL files in the same directory:
- opus.dll (renamed from libopus-0.dll)
- libwinpthread-1.dll
- libgcc_s_sjlj-1.dll  

These can be obtained from the 'opusfile' download at http://opus-codec.org/downloads/

Requires pyaudio:
https://people.csail.mit.edu/hubert/pyaudio/

### Required Python packages
```
pip3 install pycryptodome  
pip3 install pyaudio  
pip3 install pulsectl  
pip3 install websocket-client  
pip3 install numpy --upgrade  
pip3 install opuslib  
pip3 install librosa
```

### Installing librosa on a Raspberry Pi
```
sudo apt-get install llvm-11  
LLVM_CONFIG=llvm-config-11 pip3 install llvmlite  
LLVM_CONFIG=llvm-config-11 pip3 install librosa  
sudo apt-get install libblas-dev  
sudo apt-get install libatlas-base-dev
```

## Using zellostream.py with trunk-recorder
The [simplestream plugin](https://github.com/robotastic/trunk-recorder/blob/master/docs/CONFIGURE.md#simplestream-plugin) of trunk-recorder can be be used to send audio from trunk-recorder in real time, as it is being recorded.  zellostream.py can receive this audio and stream it to Zello with low latency.

zellostream.py sends audio to zello in the order recieved via UDP packets with no mixing or delays.  Therefore, only a single talkgroup should be sent to Zello using this method.  If audio from more than one talkgroup is sent and both are active at the same time, the audio from the two talkgroups will be interleaved and unintelligible.

A single talkgroup can be streamed in one of two ways:
- Configure the trunk-recorder simplestream plugin to only send audio from a single talkgroup with the "sendTGID" parameter set to false in the simplestream configuration.  In the zellostreamUDP.py config.json file, set TGID_in_stream to false.
- Configure the trunk-recorder simplesstream plugin to send audio from multiple talkgroups with the "sendTGID" parameter set to true in the simplestream configuration.  In the zellostreamUDP.py config.json file, set TGID_in_stream to true and TGID_to_play to the desired talkgroup ID to stream.
