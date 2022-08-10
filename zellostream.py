import sys
import websocket
import json
import time
import pyaudio
import numpy as np
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
    config["vox_silence_time"] = configdata.get("vox_silence_time", 3)
    config["in_channel_config"] = configdata.get("in_channel", "mono")
    issuer = configdata.get("issuer")
    if not issuer:
        raise ConfigException("ERROR GETTING ZELLO ISSUER ID FROM CONFIG FILE")
    config["issuer"] = issuer
    zello_channel = configdata.get("zello_channel")
    if not zello_channel:
        raise ConfigException("ERROR GETTING ZELLO CHANNEL NAME FROM CONFIG FILE")
    config["zello_channel"] = zello_channel
    config["audio_threshold"] = configdata.get("audio_threshold", 1000)
    config["input_device_index"] = configdata.get("input_device_index", 0)
    config["audio_sample_rate"] = configdata.get("audio_sample_rate", 48000)
    config["audio_channels"] = configdata.get("audio_channels", 1)
    config["zello_sample_rate"] = configdata.get("audio_sample_rate", 16000)
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


def start_audio(config, p):
    audio_chunk = int(config["audio_sample_rate"] * 0.06)  # 60ms = 960 samples @ 16000 S/s
    format = pyaudio.paInt16
    print("start_audio: open audio")
    stream = p.open(
        format=format,
        channels=config["audio_channels"],
        rate=config["audio_sample_rate"],
        input=True,
        output=True,
        frames_per_buffer=audio_chunk,
        input_device_index=config["input_device_index"],
    )
    print("start_audio: audio opened")
    return stream


def record(config, stream, seconds, channel="mono"):
    alldata = bytearray()
    audio_chunk = int(config["audio_sample_rate"] * 0.06)
    for i in range(0, int(config["audio_sample_rate"] / audio_chunk * seconds)):
        data = stream.read(audio_chunk)
        alldata.extend(data)
    data = np.frombuffer(alldata, dtype=np.short)
    if config["audio_sample_rate"] != config["zello_sample_rate"]:
        zello_data = librosa.resample(data, config["audio_sample_rate"], config["zello_sample_rate"])
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
        print("create_zello_connection: seq:", data.get("seq"))
        seq_num = seq_num + 1
        return ws
    except Exception as ex:
        print(f"create_zello_connection: exception: {ex}")
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
        config["zello_sample_rate"].to_bytes(2, "little") + frames_per_packet.to_bytes(1, "big") + packet_duration.to_bytes(1, "big")
    ).decode()
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
                if seq_num > start_seq_num + 8:
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
            if seq_num > start_seq_num + 8:
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


def create_encoder(config):
    return opuslib.api.encoder.create_state(config["zello_sample_rate"], config["audio_channels"], opuslib.APPLICATION_AUDIO)


def main():
    try:
        config = get_config()
    except ConfigException as ex:
        print(f"Configuration error: {ex}")
        sys.exit(1)

    print("Importing librosa...")
    import librosa
    print("Imported librosa")
    print("Start PyAudio")
    p = pyaudio.PyAudio()
    print("Started PyAudio")
    audio_stream = start_audio(config, p)
    zello_chunk = int(config["zello_sample_rate"] * 0.06)
    enc = create_encoder(config)

    stream_id = None
    processing = True
    zello_ws = None

    while processing:
        try:
            data = record(config, audio_stream, seconds=0.06, channel=config["in_channel_config"])
            max_audio_level = max(abs(data))
            if max_audio_level > config["audio_threshold"]: # Start sending to channel
                print("Audio on")
                if not zello_ws or not zello_ws.connected:
                    zello_ws = create_zello_connection(config)
                    if not zello_ws:
                        print("Cannot establish connection")
                        time.sleep(1)
                        continue
                zello_ws.settimeout(1)
                stream_id = start_stream(config, zello_ws)
                if not stream_id:
                    print("Cannot start stream")
                    time.sleep(1)
                    continue
                print("sending to stream_id " + str(stream_id))
                packet_id = 0  # packet ID is only used in server to client - populate with zeros for client to server direction
                quiet_samples = 0
                timer = time.time()
                while quiet_samples < (config["vox_silence_time"] * (1 / 0.06)):
                    if time.time() - timer > 30:
                        print("Timer break")
                        stop_stream(zello_ws, stream_id)
                        stream_id = start_stream(config, zello_ws)
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
                    data = record(config, audio_stream, 0.06, channel=config["in_channel_config"])
                    max_audio_level = max(abs(data))
                    if max_audio_level < config["audio_threshold"]:
                        quiet_samples = quiet_samples + 1
                    else:
                        quiet_samples = 0
                print("Done sending audio")
                stop_stream(zello_ws, stream_id)
                stream_id = None
            else: # Monitor channel for incoming traffic
                if not zello_ws or not zello_ws.connected:
                    zello_ws = create_zello_connection(config)
                    if not zello_ws:
                        print("Cannot establish connection")
                        time.sleep(1)
                        continue
                try:
                    zello_ws.settimeout(0.05)
                    result = zello_ws.recv()
                    print(f"Recv: {result}")
                    data = json.loads(result)
                    # TODO: look for on_stream_start command to receive audio stream
                except Exception as ex:
                    pass
        except KeyboardInterrupt:
            print("Keyboard interrupt caught")
            if stream_id:
                print("Stop sending audio")
                stop_stream(zello_ws, stream_id)
                stream_id = None
            processing = False

    print("Terminating")
    if zello_ws:
        zello_ws.close()
    audio_stream.close()
    p.terminate()


if __name__ == "__main__":
    main()
