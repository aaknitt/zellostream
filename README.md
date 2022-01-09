# zellostream
Python scripts to stream audio one way to a Zello channel.  Designed for Python 3.X

Two scripts are provided.  zellostream.py acquires audio from a sound card to send to Zello.  zellostreamUDP.py acquires audio from a UDP socket (intended for use with trunk-recorder and the simplstream plugin).  

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

## config.json
- username:  Zello account username to use for streaming
- password:  Zello account password to use for streaming
- zello_channel:  name of the zello channel to stream to
- issuer:  Issuer credential from Zello account (see above)
- vox_silence_time:  Time in seconds of detected silence before streaming stops
- audio_threshold:  Audio detected above this level will be streamed
- input_device_index:  Index of the audio input device to use for streaming (not used in zellostreamUDP.py)
- TGID_in_stream: When true, a four-byte talkgroup ID is expected prior to the audio data in each incoming UDP packet and only the talkgroup specified in TGID_to_play will be streamed.  Default is false.  (only used in zellostreamUDP.py)
- TGID_to_play: When TGID_in_stream is set to true, the integer in this field specifies which talkgroup ID will be streamed (only used in zellostreamUDP.py)
- UDP_PORT: UDP port to listen for oncompressed PCM audio on.  Audio received on this port will be compressed and streamed to Zello (only used in zeelostreamUDP.py)

## Dependencies
On Windows, requires these DLL files in the same directory:
- opus.dll (renamed from libopus-0.dll)
- libwinpthread-1.dll
- libgcc_s_sjlj-1.dll
These can be obtained from the 'opusfile' download at http://opus-codec.org/downloads/

Requires websocket_client:
https://pypi.org/project/websocket_client/

Requires pyaudio:
https://people.csail.mit.edu/hubert/pyaudio/

## Using zellostreamUDP.py with trunk-recorder
The simplstream plugin of trunk-recorder can be be used to send audio from trunk-recorder in real time, as it is being recorded.  zellostreamUDP.py can receive this audio and stream it to Zello with low latency.  

zellostreamUDP.py sends audio to zello in the order recieved via UDP packets with no mixing or delays.  Therefore, only a single talkgroup should be sent to Zello using this method.  If audio from more than one talkgroup is sent and both are active at the same time, the audio from the two talkgroups will be interleaved and unintelligible.  

A single talkgroup can be streamed in one of two ways:
- Configure the trunk-recorder simplestream plugin to only send audio from a single talkgroup with the "sendTGID" parameter set to false in the simplestream configuration.  In the zellostreamUDP.py config.json file, set TGID_in_stream to false.  
- Configure the trunk-recorder simplesstream plugin to send audio from multiple talkgroups with the "sendTGID" parameter set to true in the simplestream configuration.  In the zellostreamUDP.py config.json file, set TGID_in_stream to true and TGID_to_play to the desired talkgroup ID to stream.  
