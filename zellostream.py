import sys
import subprocess
import websocket
import socket
import json
import time
import logging
import pyaudio
import numpy as np
import opuslib
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256
import base64
from threading import Thread,Lock

logging.basicConfig(format='%(asctime)s %(levelname).1s %(funcName)s: %(message)s', level=logging.INFO)
LOG = logging.getLogger('Zellostream')

LOG.info("Importing librosa...")
import librosa
LOG.info("Imported librosa")

from pulseaudio import PulseAudioHandler

"""On Windows, requires these DLL files in the same directory:
opus.dll (renamed from libopus-0.dll)
libwinpthread-1.dll
libgcc_s_sjlj-1.dll
These can be obtained from the 'opusfile' download at http://opus-codec.org/downloads/
"""

seq_num = 0


class ConfigException(Exception):
	pass


def get_config():
	config = {}
	f = open("privatekey.pem", "r")
	config["key"] = RSA.import_key(f.read())
	f.close()

	with open("config.json") as f:
		configdata = json.load(f)

	username = configdata.get("username")
	if not username:
		raise ConfigException("ERROR GETTING USERNAME FROM CONFIG FILE")
	config["username"] = username
	password = configdata.get("password")
	if not password:
		raise ConfigException("ERROR GETTING PASSWORD FROM CONFIG FILE")
	config["password"] = password
	issuer = configdata.get("issuer")
	if not issuer:
		raise ConfigException("ERROR GETTING ZELLO ISSUER ID FROM CONFIG FILE")
	config["issuer"] = issuer
	zello_channel = configdata.get("zello_channel")
	if not zello_channel:
		raise ConfigException("ERROR GETTING ZELLO CHANNEL NAME FROM CONFIG FILE")
	config["zello_channel"] = zello_channel
	config["vox_silence_time"] = configdata.get("vox_silence_time", 3)
	config["audio_threshold"] = configdata.get("audio_threshold", 1000)
	config["input_device_index"] = configdata.get("input_device_index", 0)
	config["input_pulse_name"] = configdata.get("input_pulse_name")
	config["output_device_index"] = configdata.get("output_device_index", 0)
	config["output_pulse_name"] = configdata.get("output_pulse_name")
	config["audio_input_sample_rate"] = configdata.get("audio_input_sample_rate", 48000)
	config["audio_input_channels"] = configdata.get("audio_input_channels", 1)
	config["zello_input_sample_rate"] = configdata.get("zello_input_sample_rate", 16000)
	config["audio_output_sample_rate"] = configdata.get("audio_output_sample_rate", 48000)
	config["audio_output_channels"] = configdata.get("audio_output_channels", 1)
	config["audio_output_volume"] = configdata.get("audio_output_volume", 1)
	config["in_channel_config"] = configdata.get("in_channel", "mono")
	config["audio_source"] = configdata.get("audio_source","sound_card")
	config["ptt_on_command"] = configdata.get("ptt_on_command")
	config["ptt_off_command"] = configdata.get("ptt_off_command")
	config["ptt_off_delay"] =  configdata.get("ptt_off_delay", 2)
	config["ptt_command_support"] = not (config["ptt_on_command"] is None or config["ptt_off_command"] is None)
	config["logging_level"] = configdata.get("logging_level", "warning")
	config["udp_port"] = configdata.get("UDP_PORT",9123)
	config["tgid_in_stream"] = configdata.get("TGID_in_stream",False)
	config["tgid_to_play"] = configdata.get("TGID_to_play",70000)
	return config


def create_zello_jwt(config):
	# Create a Zello-specific JWT.  Can't use PyJWT because Zello doesn't support url safe base64 encoding in the JWT.
	header = {"typ": "JWT", "alg": "RS256"}
	payload = {"iss": config["issuer"], "exp": round(time.time() + 60)}
	signer = pkcs1_15.new(config["key"])
	json_header = json.dumps(header, separators=(",", ":"), cls=None).encode("utf-8")
	json_payload = json.dumps(payload, separators=(",", ":"), cls=None).encode("utf-8")
	h = SHA256.new(base64.standard_b64encode(json_header) + b"." + base64.standard_b64encode(json_payload))
	signature = signer.sign(h)
	jwt = base64.standard_b64encode(json_header) + b"." + base64.standard_b64encode(json_payload) + b"." + base64.standard_b64encode(signature)
	return jwt


def EscapeAll(inbytes):
	if type(inbytes) == str:
		return inbytes
	else:
		return "b'{}'".format("".join("\\x{:02x}".format(b) for b in inbytes))


def get_default_input_audio_index(config, p):
	info = p.get_host_api_info_by_index(0)
	numdevices = info.get('deviceCount')
	output_device_names={}
	for i in range (0,numdevices):
		if p.get_device_info_by_host_api_device_index(0,i).get('maxOutputChannels')>0:
			device_info = p.get_device_info_by_host_api_device_index(0,i)
			output_device_names[device_info["name"]] = device_info["index"]
	return output_device_names.get("default", config["output_device_index"])


def get_default_output_audio_index(config, p):
	info = p.get_host_api_info_by_index(0)
	numdevices = info.get('deviceCount')
	input_device_names={}
	for i in range (0,numdevices):
		if p.get_device_info_by_host_api_device_index(0,i).get('maxInputChannels')>0:
			device_info = p.get_device_info_by_host_api_device_index(0,i)
			input_device_names[device_info["name"]] = device_info["index"]
	return input_device_names.get("default", config["input_device_index"])


def start_audio(config, p):
	audio_chunk = int(config["audio_input_sample_rate"] * 0.06)  # 60ms = 960 samples @ 16000 S/s
	format = pyaudio.paInt16
	LOG.debug("open audio")
	if "input_pulse_name" in config or "output_pulse_name" in config: # using pulseaudio
		pulse = PulseAudioHandler()
	# Audio input
	if "input_pulse_name" in config: # using pulseaudio for input
		input_device_index = get_default_input_audio_index(config, p) # get default device first
	else: # use pyaudio device number
		input_device_index = config["input_device_index"]
	input_stream = p.open(
		format=format,
		channels=config["audio_input_channels"],
		rate=config["audio_input_sample_rate"],
		input=True,
		frames_per_buffer=audio_chunk,
		input_device_index=input_device_index,
	)
	LOG.debug("audio input opened")
	if "input_pulse_name" in config: # redirect input to zellostream with pulseaudio
		pulse_source_index = pulse.get_source_index(config["input_pulse_name"])
		pulse_source_output_index = pulse.get_own_source_output_index()
		if pulse_source_index is None or pulse_source_output_index is None:
			LOG.warning(
				"cannot move source output %d to source %d",
				pulse_source_output_index,
				pulse_source_index
			)
		else:
			try:
				pulse.move_source_output(pulse_source_output_index, pulse_source_index)
				LOG.debug(
					"moved pulseaudio source output %d to source %d",
					pulse_source_output_index,
					pulse_source_index
				)
			except Exception as ex:
				LOG.error("exception assigning pulseaudio source: %s", ex)
	# Audio outpput
	if "output_pulse_name" in config: # using pulseaudio for output
		output_device_index = get_default_output_audio_index(config, p)
	else: # use pyaudio device number
		output_device_index = config["output_device_index"]
	output_stream = p.open(
		format=format,
		channels=config["audio_output_channels"],
		rate=config["audio_output_sample_rate"],
		output=True,
		frames_per_buffer=audio_chunk,
		output_device_index=output_device_index,
	)
	LOG.debug("audio output opened")
	if "output_pulse_name" in config: # redirect output from zellostream with pulseaudio
		pulse_sink_index = pulse.get_sink_index(config["output_pulse_name"])
		pulse_sink_input_index = pulse.get_own_sink_input_index()
		if pulse_sink_index is None or pulse_sink_input_index is None:
			LOG.warning(
				"cannot move pulseaudio sink input %d to sink %d",
				pulse_sink_input_index,
				pulse_sink_index
			)
		else:
			try:
				pulse.move_sink_input(pulse_sink_input_index, pulse_sink_index)
				LOG.debug(
					"moved pulseaudio sink input %d to sink %d",
					pulse_sink_input_index,
					pulse_sink_index
				)
			except Exception as ex:
				LOG.error("exception assigning pulseaudio sink: %s", ex)
	return input_stream, output_stream


def record_chunk(config, stream, channel="mono"):
	audio_chunk = int(config["audio_input_sample_rate"] * 0.06)
	alldata = bytearray()
	data = stream.read(audio_chunk)
	alldata.extend(data)
	data = np.frombuffer(alldata, dtype=np.short)
	if config["audio_input_sample_rate"] != config["zello_input_sample_rate"]:
		zello_data = librosa.resample(data.astype(np.float32), orig_sr=config["audio_input_sample_rate"], target_sr=config["zello_input_sample_rate"]).astype(np.short)
	else:
		zello_data = data
	if channel == "left":
		zello_data = zello_data[0::2]
	elif channel == "right":
		zello_data = zello_data[1::2]
	elif channel == "mix":
		zello_data = (zello_data[0::2] + zello_data[1::2]) / 2
	else:
		zello_data = zello_data
	return zello_data

def udp_rx(sock,config):
	global udpdata
	while processing:
		try:
			newdata,addr = sock.recvfrom(4096)
			if config['TGID_in_stream']:
				tgid = int.from_bytes(newdata[0:4],"little")
				LOG.debug("got %d bytes from %s for THID %d", len(newdata), addr, tgid)
				if tgid == config['TGID_to_play']:
					newdata = newdata[4:]
				else:
					newdata = b''
			else:
				LOG.debug("got %d bytes frim %s", len(newdata), addr)
			with udp_buffer_lock:
				udpdata = udpdata + newdata
		except socket.timeout:
			pass

def get_udp_audio(config,seconds,channel="mono"):
	global udpdata,udp_buffer_lock
	num_bytes = int(seconds*config["audio_input_sample_rate"]*2)  #.06 seconds * 8000 samples per second * 2 bytes per sample => 960 bytes per 60 ms
	if channel != "mono":
		num_bytes = num_bytes *2
	with udp_buffer_lock:
		data = np.frombuffer(udpdata[:num_bytes], dtype=np.short)
		udpdata = udpdata[num_bytes:]
	if config["audio_input_sample_rate"] != config["zello_input_sample_rate"]:
		zello_data = librosa.resample(data.astype(np.float32), orig_sr=config["audio_input_sample_rate"], target_sr=config["zello_input_sample_rate"]).astype(np.short)
	else:
		zello_data = data
	if channel == "left":
		zello_data = zello_data[0::2]
	elif channel == "right":
		zello_data = zello_data[1::2]
	elif channel == "mix":
		zello_data = (zello_data[0::2] + zello_data[1::2]) / 2
	else:
		zello_data = zello_data
	return zello_data

def create_zello_connection(config):
	try:
		ws = websocket.create_connection("wss://zello.io/ws")
		ws.settimeout(1)
		global seq_num
		seq_num = 1
		send = {}
		send["command"] = "logon"
		send["seq"] = seq_num
		encoded_jwt = create_zello_jwt(config)
		send["auth_token"] = encoded_jwt.decode("utf-8")
		send["username"] = config["username"]
		send["password"] = config["password"]
		send["channel"] = config["zello_channel"]
		ws.send(json.dumps(send))
		result = ws.recv()
		data = json.loads(result)
		LOG.info("seq: %d", data.get("seq"))
		seq_num = seq_num + 1
		return ws
	except Exception as ex:
		LOG.error("exception: %s", ex)
		return None


def start_stream(config, ws):
	global seq_num
	start_seq_num = seq_num
	send = {}
	send["command"] = "start_stream"
	send["channel"] = config["zello_channel"]
	send["seq"] = seq_num
	seq_num = seq_num + 1
	send["type"] = "audio"
	send["codec"] = "opus"
	# codec_header:
	# base64 encoded 4 byte string: first 2 bytes for sample rate, 3rd for number of frames per packet (1 or 2), 4th for the frame size
	# gd4BPA==  => 0x80 0x3e 0x01 0x3c  => 16000 Hz, 1 frame per packet, 60 ms frame size
	frames_per_packet = 1
	packet_duration = 60
	codec_header = base64.b64encode(
		config["zello_input_sample_rate"].to_bytes(2, "little") + frames_per_packet.to_bytes(1, "big") + packet_duration.to_bytes(1, "big")
	).decode()
	send["codec_header"] = codec_header
	send["packet_duration"] = packet_duration
	try:
		ws.send(json.dumps(send))
	except Exception as ex:
		LOG.error("send exception %s", ex)
	while True:
		try:
			result = ws.recv()
			data = json.loads(result)
			LOG.debug("data: %s", data)
			if "error" in data.keys():
				LOG.warning("error %s", data["error"])
				if seq_num > start_seq_num + 8:
					LOG.warning("bailing out")
					return None
				time.sleep(0.5)
				send["seq"] = seq_num
				seq_num = seq_num + 1
				ws.send(json.dumps(send))
			if "stream_id" in data.keys():
				stream_id = int(data["stream_id"])
				return stream_id
		except Exception as ex:
			LOG.error("exception %s", ex)
			if seq_num > start_seq_num + 8:
				LOG.warning("bailing out")
				return None
			time.sleep(0.5)
			send["seq"] = seq_num
			seq_num = seq_num + 1
			try:
				ws.send(json.dumps(send))
			except Exception as ex:
				LOG.error("send exception %s", ex)
				return None


def stop_stream(ws, stream_id):
	try:
		send = {}
		send["command"] = "stop_stream"
		send["stream_id"] = stream_id
		ws.send(json.dumps(send))
	except Exception as ex:
		LOG.error("exception: %s", {ex})


def create_encoder(config):
	return opuslib.api.encoder.create_state(config["zello_input_sample_rate"], config["audio_input_channels"], opuslib.APPLICATION_AUDIO)


def create_decoder(sample_rate):
	return opuslib.api.decoder.create_state(sample_rate, 1)


def bytes_to_uint32(bytes):
	return bytes[0]*(1<<24) + bytes[1]*(1<<16) + bytes[2]*(1<<8) + bytes[3]


def run_ptt_command(msg, command_list, delay):
	command = " ".join(command_list)
	LOG.debug("%s after %.1f seconds", command, delay)
	time.sleep(delay)
	run_command = subprocess.run(command, shell=True)
	LOG.info("%s exited with code %d", msg, run_command.returncode)


def stream_to_zello(config, zello_ws, audio_input_stream, data):
	try:
		stream_id = start_stream(config, zello_ws)
		if not stream_id:
			LOG.warning("cannot start stream")
			time.sleep(1)
			return stream_id
		LOG.info("sending to stream_id %d", stream_id)
		enc = create_encoder(config)
		zello_chunk = int(config["zello_input_sample_rate"] * 0.06)
		packet_id = 0  # packet ID is only used in server to client - populate with zeros for client to server direction
		quiet_samples = 0
		timer = time.time()
		while quiet_samples < (config["vox_silence_time"] * (1 / 0.06)):
			if time.time() - timer > 30:
				LOG.info("timer break")
				stop_stream(zello_ws, stream_id)
				stream_id = start_stream(config, zello_ws)
				if not stream_id:
					LOG.warning("cannot start stream")
					break
				timer = time.time()
			if len(data) > 0:
				data2 = data.tobytes()
				out = opuslib.api.encoder.encode(enc, data2, zello_chunk, len(data2) * 2)
				send_data = bytearray(np.array([1]).astype(">u1").tobytes())
				send_data = send_data + np.array([stream_id]).astype(">u4").tobytes()
				send_data = send_data + np.array([packet_id]).astype(">u4").tobytes()
				send_data = send_data + out
				try:
					nbytes = zello_ws.send_binary(send_data)
					if nbytes == 0:
						LOG.warning("binary send error")
						break
				except Exception as ex:
					LOG.error("Zello error %s", ex)
					break
			if config["audio_source"] == "sound_card":
				data = record_chunk(config, audio_input_stream, channel=config["in_channel_config"])
			elif config["audio_source"] == "UDP":
				data = get_udp_audio(config,seconds=0.06, channel=config["in_channel_config"])
			else:
				data = np.frombuffer(b'',dtype=np.short)
			if len(data) > 0:
				max_audio_level = max(abs(data))
			else:
				max_audio_level = 0
			if len(data) == 0 or max_audio_level < config["audio_threshold"]:
				quiet_samples = quiet_samples + 1
			else:
				quiet_samples = 0
		LOG.info("done sending audio")
		if stream_id:
			stop_stream(zello_ws, stream_id)
			stream_id = None
	finally:
		return stream_id


def stream_from_zello(config, zello_ws, audio_output_stream, start_data):
	if "codec_header" not in start_data:
		return
	packet_duration = start_data.get("packet_duration", 0)
	b64x = base64.b64decode(start_data["codec_header"])
	sample_rate = b64x[1]*256 + b64x[0]
	frames_per_buffer = b64x[2]
	frame_duration = b64x[3]
	zello_chunk = (sample_rate * packet_duration) // 1000
	dec = create_decoder(sample_rate)
	LOG.info(
		"start of bytes stream: sample_rate: %d frames_per_buffer: %d frame_duration: %d packet_duration: %d",
		sample_rate,
		frames_per_buffer,
		frame_duration,
		packet_duration
	)
	if config["ptt_command_support"]:
		run_ptt_command("PTT on", config["ptt_on_command"], 0)
	while True:
		try:
			received = zello_ws.recv()
			if type(received) == bytes:
				if received[0] == 1: # audio
					stream_id = bytes_to_uint32(received[1:5])
					packet_id = bytes_to_uint32(received[5:9])
					data_length = len(received) - 9
					data = received[9:]
					# print(f"stream_from_zello: {stream_id}:{packet_id} data length: {data_length}")
					audio = opuslib.api.decoder.decode(dec, data, data_length, zello_chunk, False, 1)
					# print(f"stream_from_zello: audio length: {len(audio)}")
					vol_adjust = config["audio_output_volume"] / config["audio_output_channels"]
					np_audio = np.repeat(np.frombuffer(audio, dtype=np.short), config["audio_output_channels"]) * vol_adjust
					if sample_rate != config["audio_output_sample_rate"]:
						audio_out = librosa.resample(np_audio.astype(np.float32), orig_sr=sample_rate, target_sr=config["audio_output_sample_rate"]).astype(np.short)
						audio_output_stream.write(audio_out.tobytes())
					else:
						audio_output_stream.write(np_audio.astype(np.short).toBytes())
			else:
				LOG.info("end of bytes stream")
				if config["ptt_command_support"]:
					run_ptt_command("PTT off", config["ptt_off_command"], config["ptt_off_delay"])
				return # can only be an on_stream_stop if not binary
		except Exception as ex:
			LOG.error("exception: %s", ex)
			if config["ptt_command_support"]:
				run_ptt_command("PTT off", config["ptt_off_command"], config["ptt_off_delay"])
			return


def main():
	global udpdata,processing,udp_buffer_lock
	stream_id = None
	processing = True
	zello_ws = None
	udpdata = b''

	try:
		config = get_config()
	except ConfigException as ex:
		LOG.critical("configuration error: %s", ex)
		sys.exit(1)

	log_level = logging.getLevelName(config["logging_level"].upper())
	LOG.setLevel(log_level)

	if config["audio_source"] == "sound_card":
		LOG.debug("start PyAudio")
		p = pyaudio.PyAudio()
		LOG.debug("started PyAudio")
		audio_input_stream, audio_output_stream = start_audio(config, p)
	elif config["audio_source"] == "UDP":
		# Set up a UDP server to receive audio from trunk-recorder
		UDPSock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
		UDPSock.settimeout(.5)
		listen_addr = ("",config["udp_port"])
		UDPSock.bind(listen_addr)
		udp_rx_thread = Thread(target=udp_rx,args=(UDPSock,config))
		udp_rx_thread.start()
		udp_buffer_lock = Lock()
	else:
		LOG.warning("Invalid Audio Source")

	while processing:
		try:
			if config["audio_source"] == "sound_card":
				data = record_chunk(config, audio_input_stream, channel=config["in_channel_config"])
			elif config["audio_source"] == "UDP":
				data = get_udp_audio(config,seconds=0.06, channel=config["in_channel_config"])
			else:
				data = np.frombuffer(b'',dtype=np.short)
			if len(data) > 0:
				max_audio_level = max(abs(data))
			else:
				max_audio_level = 0
			if len(data) > 0 and max_audio_level > config["audio_threshold"]: # Start sending to channel
				LOG.info("audio on")
				if not zello_ws or not zello_ws.connected:
					zello_ws = create_zello_connection(config)
					if not zello_ws:
						LOG.warning("cannot establish connection")
						time.sleep(1)
						continue
				zello_ws.settimeout(1)
				stream_id = stream_to_zello(config, zello_ws, audio_input_stream, data)
			else: # Monitor channel for incoming traffic
				if not zello_ws or not zello_ws.connected:
					zello_ws = create_zello_connection(config)
					if not zello_ws:
						LOG.warning("cannot establish connection for incoming")
						time.sleep(1)
						continue
				try:
					zello_ws.settimeout(0.05)
					result = zello_ws.recv()
					LOG.debug("recv: %s", result)
					data = json.loads(result)
					if "command" in data and data["command"] == "on_stream_start" : # look for on_stream_start command to receive audio stream
						zello_ws.settimeout(1)
						stream_from_zello(config, zello_ws, audio_output_stream, data)
				except Exception as ex:
					pass
		except KeyboardInterrupt:
			LOG.error("keyboard interrupt caught")
			if stream_id:
				LOG.info("stop sending audio")
				stop_stream(zello_ws, stream_id)
				stream_id = None
			processing = False

	LOG.info("terminating")
	if zello_ws:
		zello_ws.close()
	if config["audio_source"] == "sound_card":
		audio_input_stream.close()
		audio_output_stream.close()
		p.terminate()
	elif config["audio_source"] == "UDP":
		time.sleep(1)
		UDPSock.close()



if __name__ == "__main__":
	main()
