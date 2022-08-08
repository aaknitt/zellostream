import websocket
import json
import time
import pyaudio
import numpy as np
import librosa
import opuslib
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256
import base64

"""On Windows, requires these DLL files in the same directory:
opus.dll (renamed from libopus-0.dll)
libwinpthread-1.dll
libgcc_s_sjlj-1.dll
These can be obtained from the 'opusfile' download at http://opus-codec.org/downloads/
"""

f = open("privatekey.pem", "r")
key = RSA.import_key(f.read())
f.close()

with open("config.json") as f:
    configdata = json.load(f)

username = configdata.get("username")
if not username:
    print("ERROR GETTING USERNAME FROM CONFIG FILE")
password = configdata.get("password")
if not password:
    print("ERROR GETTING PASSWORD FROM CONFIG FILE")
vox_silence_time = configdata.get("vox_silence_time", 3)
in_channel_config = configdata.get("in_channel", "mono")
issuer = configdata.get("issuer")
if not issuer:
    print("ERROR GETTING ZELLO ISSUER ID FROM CONFIG FILE")
zello_channel = configdata.get("zello_channel")
if not zello_channel:
    print("ERROR GETTING ZELLO CHANNEL NAME FROM CONFIG FILE")
audio_threshold = configdata.get("audio_threshold", 1000)
input_device_index = configdata.get("input_device_index", 0)
audio_sample_rate = configdata.get("audio_sample_rate", 48000)
zello_sample_rate = configdata.get("audio_sample_rate", 16000)


def create_zello_jwt():
    # Create a Zello-specific JWT.  Can't use PyJWT because Zello doesn't support url safe base64 encoding in the JWT.
    header = {"typ": "JWT", "alg": "RS256"}
    payload = {"iss": issuer, "exp": round(time.time() + 60)}
    signer = pkcs1_15.new(key)
    json_header = json.dumps(header, separators=(",", ":"), cls=None).encode("utf-8")
    json_payload = json.dumps(payload, separators=(",", ":"), cls=None).encode("utf-8")
    h = SHA256.new(
        base64.standard_b64encode(json_header)
        + b"."
        + base64.standard_b64encode(json_payload)
    )
    signature = signer.sign(h)
    jwt = (
        base64.standard_b64encode(json_header)
        + b"."
        + base64.standard_b64encode(json_payload)
        + b"."
        + base64.standard_b64encode(signature)
    )
    return jwt


def EscapeAll(inbytes):
    if type(inbytes) == str:
        return inbytes
    else:
        return "b'{}'".format("".join("\\x{:02x}".format(b) for b in inbytes))


print("Start PyAudio")
p = pyaudio.PyAudio()
audio_chunk = int(audio_sample_rate * 0.06) # 60ms = 960 samples @ 16000 S/s
zello_chunk = int(zello_sample_rate * 0.06)
FORMAT = pyaudio.paInt16
CHANNELS = 1
print("Open audio")
stream = p.open(
    format=FORMAT,
    channels=CHANNELS,
    rate=audio_sample_rate,
    input=True,
    output=True,
    frames_per_buffer=audio_chunk,
    input_device_index=input_device_index,
)
print("Audio opened")


def record(seconds, channel="mono"):
    alldata = bytearray()
    for i in range(0, int(audio_sample_rate / audio_chunk * seconds)):
        data = stream.read(audio_chunk)
        alldata.extend(data)
    data = np.frombuffer(alldata, dtype=np.short)
    if audio_sample_rate != zello_sample_rate:
        zello_data = librosa.resample(data, audio_sample_rate, zello_sample_rate)
    else:
        zello_data = data
    if channel == "left":
        zello_data = zello_data[0::2]
    elif channel == "right":
        zello_data = zello_data[1::2]
    else:
        zello_data = zello_data
    return zello_data


seq_num = 0


def create_zello_connection():
    try:
        ws = websocket.create_connection("wss://zello.io/ws")
        ws.settimeout(1)
        global seq_num
        seq_num = 1
        send = {}
        send["command"] = "logon"
        send["seq"] = seq_num
        encoded_jwt = create_zello_jwt()
        send["auth_token"] = encoded_jwt.decode("utf-8")
        send["username"] = username
        send["password"] = password
        send["channel"] = zello_channel
        ws.send(json.dumps(send))
        result = ws.recv()
        data = json.loads(result)
        print("create_zello_connection: seq:", data.get("seq"))
        seq_num = seq_num + 1
        return ws
    except Exception as ex:
        print(f"create_zello_connection: exception: {ex}")
        return None


def start_stream(ws):
    global seq_num
    send = {}
    send["command"] = "start_stream"
    send["channel"] = zello_channel
    send["seq"] = seq_num
    seq_num = seq_num + 1
    send["type"] = "audio"
    send["codec"] = "opus"
    # codec_header:
    # base64 encoded 4 byte string: first 2 bytes for sample rate, 3rd for number of frames per packet (1 or 2), 4th for the frame size
    # gd4BPA==  => 0x80 0x3e 0x01 0x3c  => 16000 Hz, 1 frame per packet, 60 ms frame size
    frames_per_packet = 1
    packet_duration = 60
    codec_header = base64.b64encode(zello_sample_rate.to_bytes(2, "little") + frames_per_packet.to_bytes(1, "big") + packet_duration.to_bytes(1, "big")).decode()
    send["codec_header"] = codec_header
    send["packet_duration"] = packet_duration
    try:
        ws.send(json.dumps(send))
    except Exception as ex:
        print(f"start_stream: send exception {ex}")
    while True:
        try:
            result = ws.recv()
            data = json.loads(result)
            print("start_stream: data:", data)
            if "error" in data.keys():
                print("start_stream: error", data["error"])
                if seq_num > 10:
                    print("start_stream: bailing out")
                    return None
                time.sleep(0.5)
                send["seq"] = seq_num
                seq_num = seq_num + 1
                ws.send(json.dumps(send))
            if "stream_id" in data.keys():
                stream_id = int(data["stream_id"])
                return stream_id
        except Exception as ex:
            print(f"start_stream: exception {ex}")
            if seq_num > 10:
                print("start_stream: bailing out")
                return None
            time.sleep(0.5)
            send["seq"] = seq_num
            seq_num = seq_num + 1
            try:
                ws.send(json.dumps(send))
            except Exception as ex:
                print(f"start_stream: send exception {ex}")
                return None


def stop_stream(ws, stream_id):
    try:
        send = {}
        send["command"] = "stop_stream"
        send["stream_id"] = stream_id
        ws.send(json.dumps(send))
    except Exception as ex:
        print(f"stop_stream: exception: {ex}")


enc = opuslib.api.encoder.create_state(
    zello_sample_rate, CHANNELS, opuslib.APPLICATION_AUDIO
)

stream_id = None
processing = True

while processing:
    try:
        data = record(seconds=0.06, channel=in_channel_config)
        max_audio_level = max(abs(data))
        # print(f"Init max_audio_level: {max_audio_level}")
        if max_audio_level > audio_threshold:
            print("Audio on")
            zello_ws = create_zello_connection()
            if not zello_ws:
                print("Cannot establish connection")
                time.sleep(1)
                continue
            stream_id = start_stream(zello_ws)
            if not stream_id:
                print("Cannot start stream")
                time.sleep(1)
                continue
            print("sending to stream_id " + str(stream_id))
            packet_id = 0 # packet ID is only used in server to client - populate with zeros for client to server direction
            quiet_samples = 0
            timer = time.time()
            while quiet_samples < (vox_silence_time * (1 / 0.06)):
                if time.time() - timer > 30:
                    print("Timer break")
                    stop_stream(zello_ws, stream_id)
                    stream_id = start_stream(zello_ws)
                    if not stream_id:
                        print("Cannot start stream")
                        break
                    timer = time.time()
                data2 = data.tobytes()
                out = opuslib.api.encoder.encode(enc, data2, zello_chunk, len(data2) * 2)
                send_data = bytearray(np.array([1]).astype(">u1").tobytes())
                send_data = send_data + np.array([stream_id]).astype(">u4").tobytes()
                send_data = send_data + np.array([packet_id]).astype(">u4").tobytes()
                send_data = send_data + out
                try:
                    nbytes = zello_ws.send_binary(send_data)
                    if nbytes == 0:
                        print("Binary send error")
                        break
                except Exception as ex:
                    print(f"Zello error {ex}")
                    break
                data = record(0.06, channel=in_channel_config)
                max_audio_level = max(abs(data))
                if max_audio_level < audio_threshold:
                    quiet_samples = quiet_samples + 1
                else:
                    quiet_samples = 0
            print("Done sending audio")
            stop_stream(zello_ws, stream_id)
            zello_ws.close()
            stream_id = None
    except KeyboardInterrupt:
        print("Keyboard interrupt caught")
        if stream_id:
            print("Stop sending audio")
            stop_stream(zello_ws, stream_id)
            zello_ws.close()
            stream_id = None
        processing = False

print("Terminating")
stream.close()
p.terminate()
