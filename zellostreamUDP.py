import websocket
import socket
import json
import time
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
	TGID_in_stream = configdata['TGID_in_stream']  #When set to True, we expect a 4 byte long int with the TGID prior to the audio in each packet
except:
	TGID_in_stream = False
try:
	TGID_to_play = configdata['TGID_to_play']  #When TGID_in_stream is set to True, we'll only play audio if the received TGID matches this value
except:
	TGID_to_play = 70000
try:
	UDP_PORT = configdata['UDP_PORT']  #UDP port to listen for incoming uncompressed audio
except:
	UDP_PORT = 9123
try:
	audio_sample_rate = configdata['audio_sample_rate']
except:
	audio_sample_rate = 8000
	
# Set up a UDP server to receive audio from trunk-recorder
UDPSock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
UDPSock.settimeout(.5)

listen_addr = ("",UDP_PORT)
UDPSock.bind(listen_addr)

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
	#gD4BPA==  => 0x80 0x3e 0x01 0x3C  => 16000 Hz, 1 frame per packet, 60 ms frame size
	#gD4CPA==  => 0x80 0x3e 0x02 0x3C  => 16000 Hz, 2 frames per packet, 60 ms frame size
	#QB8BPA==  => 0x40 0x1f 0x01 0x3C  => 8000 Hz, 1 frame per packet, 60 ms frame size
	if audio_sample_rate == 16000:
		send['codec_header'] = "gD4BPA=="
	else:
		send['codec_header'] = "QB8BPA=="
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
CHANNELS = 1
enc = opuslib.api.encoder.create_state(audio_sample_rate,CHANNELS,opuslib.APPLICATION_AUDIO)
stream_id = 0
quiet_samples = 0
bytes_per_60ms = .06*audio_sample_rate*2  #.06 seconds * 8000 samples per second * 2 bytes per sample => 960 bytes per 60 ms
while True:
	try:
		udpdata,addr = UDPSock.recvfrom(4096)  
		#print("Got data from ",addr)
		if TGID_in_stream:
			tgid = int.from_bytes(udpdata[0:4],"little")
			#print(tgid," ",len(udpdata))
			if tgid == TGID_to_play:
				udpdata = udpdata[4:]
			else:
				udpdata = []
		while len(udpdata)>=bytes_per_60ms:  
			data = udpdata[:bytes_per_60ms]  
			udpdata = udpdata[bytes_per_60ms:]
			datalist  = frombuffer(data, dtype='uint16')
			max_audio_level = max(abs(datalist))
			if max_audio_level > audio_threshold or stream_id != 0:
				if stream_id == 0:
					zello_ws = create_zello_connection()
					stream_id = start_stream(zello_ws)
					print("sending to stream_id " + str(stream_id))
					quiet_samples = 0
				while (quiet_samples < (vox_silence_time*(1/.06))):
					out = opuslib.api.encoder.encode(enc, data, bytes_per_60ms/2, len(data)*2)  #2 bytes per sample
					#print(len(out))
					send_data = bytearray(array([1]).astype('>u1').tobytes())
					send_data = send_data + array([stream_id]).astype('>u4').tobytes()
					send_data = send_data + array([packet_id]).astype('>u4').tobytes()  #packet ID is only used in server to client - populate with zeros for client to server direction
					send_data = send_data + out
					try:
						zello_ws.send_binary(send_data)
					except:
						break
					data = udpdata[:bytes_per_60ms] 
					udpdata = udpdata[bytes_per_60ms:]
					#print("remaining udpdata size is ",len(udpdata)," bytes")
					if len(data) == bytes_per_60ms:
						datalist = frombuffer(data, dtype='uint16')
						if abs(max(datalist)) < audio_threshold:
							quiet_samples = quiet_samples+1
						else:
							quiet_samples = 0
					else:
						break
	except socket.timeout:
		if stream_id != 0:
			print("Done sending audio")
			stop_stream(zello_ws,stream_id)
			zello_ws.close()
			stream_id = 0
stream.close()
p.terminate()