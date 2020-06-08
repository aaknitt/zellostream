import websocket
import json
import time
import pyaudio
from numpy import short, frombuffer, array
import opuslib
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256
import base64

'''On Windows, requires these DLL files in the same directory:
opus.dll (renamed from libopus-0.dll)
libwinpthread-1.dll
libgcc_s_sjlj-1.dll
These can be obtained from the 'opusfile' download at http://opus-codec.org/downloads/
'''

f = open('privatekey.pem','r')
key = RSA.import_key(f.read())
f.close()

with open('config.json') as f:
	configdata = json.load(f)

try:
	username = configdata['username']
except:
	print("ERROR GETTING USERNAME FROM CONFIG FILE")
try:
	password = configdata['password']
except:
	print("ERROR GETTING PASSWORD FROM CONFIG FILE")
try:
	vox_silence_time = configdata['vox_silence_time']
except:
	vox_silence_time = 3
try:
	in_channel_config = configdata['in_channel']
except:
	in_channel_config = 'mono'
try:
	issuer = configdata['issuer']
except:
	print("ERROR GETTING ZELLO ISSUER ID FROM CONFIG FILE")
try:
	zello_channel = configdata['zello_channel']
except:
	print("ERROR GETTING ZELLO CHANNEL NAME FROM CONFIG FILE")
try: 
	audio_threshold = configdata['audio_threshold']
except:
	audio_threshold = 1000
try:
	input_device_index = configdata['input_device_index']
except:
	input_device_index = 0

def create_zello_jwt():
	#Create a Zello-specific JWT.  Can't use PyJWT because Zello doesn't support url safe base64 encoding in the JWT.
	header = {"typ": "JWT", "alg": "RS256"}
	payload = {"iss": issuer,"exp": round(time.time()+60)}
	signer = pkcs1_15.new(key)
	json_header = json.dumps(header, separators=(",", ":"), cls=None).encode("utf-8")
	json_payload = json.dumps(payload, separators=(",",":"), cls=None).encode("utf-8")
	h = SHA256.new(base64.standard_b64encode(json_header) + b"." + base64.standard_b64encode(json_payload))
	signature = signer.sign(h)
	jwt = (base64.standard_b64encode(json_header) + b"." + base64.standard_b64encode(json_payload) + b"." + base64.standard_b64encode(signature))
	return jwt

def EscapeAll(inbytes):
	if type(inbytes) == str:
		return inbytes
	else:
		return 'b\'{}\''.format(''.join('\\x{:02x}'.format(b) for b in inbytes))

p = pyaudio.PyAudio()
chunk = 960
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
stream = p.open(format = FORMAT,
	channels = CHANNELS,
	rate = RATE,
	input = True,
	output = True,
	frames_per_buffer = chunk,
	input_device_index = input_device_index,)

def record(seconds,channel='mono'):
	alldata = bytearray()
	for i in range(0, int(RATE / chunk * seconds)):
				data = stream.read(chunk)
				alldata.extend(data)
	data  = frombuffer(alldata, dtype=short)
	if channel == 'left':
		data = data[0::2]
	elif channel == 'right':
		data = data[1::2]
	else:
		data = data
	return data

seq_num = 0
def create_zello_connection():
	ws = websocket.create_connection("wss://zello.io/ws")
	ws.settimeout(1)
	global seq_num
	seq_num = 1
	send = {}
	send['command'] = 'logon'
	send['seq'] = seq_num
	encoded_jwt = create_zello_jwt()
	send['auth_token'] = encoded_jwt.decode('utf-8')
	send['username'] = username
	send['password'] = password
	send['channel'] = zello_channel
	ws.send(json.dumps(send))
	result = ws.recv()
	data = json.loads(result)
	seq_num = seq_num + 1
	return ws

def start_stream(ws):
	global seq_num
	send = {}
	send['command'] = 'start_stream'
	send['seq'] = seq_num
	seq_num = seq_num + 1
	send['type'] = "audio"
	send['codec'] = "opus"
	#codec_header:
	#base64 encoded 4 byte string: first 2 bytes for sample rate, 3rd for number of frames per packet (1 or 2), 4th for the frame size
	#gd4BPA==  => 0x80 0x3e 0x01 0x3c  => 16000 Hz, 1 frame per packet, 60 ms frame size
	send['codec_header'] = "gD4BPA=="
	send['packet_duration'] = 60
	ws.send(json.dumps(send))
	data = {}
	while 'stream_id' not in data.keys():
		result = ws.recv()
		data = json.loads(result)
		print(data)
		if 'error' in data.keys():
			if data['error'] == 'channel is not ready':
				send['seq'] = seq_num
				seq_num = seq_num + 1
				ws.send(json.dumps(send))
	stream_id = int(data['stream_id'])
	return stream_id

def stop_stream(ws,stream_id):
	send = {}
	send['command'] = 'stop_stream'
	send['stream_id'] = stream_id
	ws.send(json.dumps(send))

start_time = time.time()
packet_id = 0

while True:
	data = record(.06)
	max_audio_level = max(abs(data))
	enc = opuslib.api.encoder.create_state(RATE,CHANNELS,opuslib.APPLICATION_AUDIO)
	if max_audio_level > audio_threshold:
		zello_ws = create_zello_connection()
		stream_id = start_stream(zello_ws)
		print("sending to stream_id " + str(stream_id))
		quiet_samples = 0
		while (quiet_samples < (vox_silence_time*(1/.06))):
			data2 = data.tobytes()
			out = opuslib.api.encoder.encode(enc, data2, chunk, len(data2)*2)
			send_data = bytearray(array([1]).astype('>u1').tobytes())
			send_data = send_data + array([stream_id]).astype('>u4').tobytes()
			send_data = send_data + array([packet_id]).astype('>u4').tobytes()  #packet ID is only used in server to client - populate with zeros for client to server direction
			send_data = send_data + out
			try:
				zello_ws.send_binary(send_data)
			except:
				break
			data = record(.06)
			if abs(max(data)) < audio_threshold:
				quiet_samples = quiet_samples+1
			else:
				quiet_samples = 0
		print("Done sending audio")
		stop_stream(zello_ws,stream_id)
		zello_ws.close()

stream.close()
p.terminate()