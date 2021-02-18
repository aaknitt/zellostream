# zellostream
Python script to stream audio one way to a Zello channel.  Designed for Python 3.X

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
- input_device_index:  Index of the audio input device to use for streaming

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

