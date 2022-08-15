import pyaudio

p = pyaudio.PyAudio()
info = p.get_host_api_info_by_index(0)
numdevices = info.get('deviceCount')
input_device_names = {}
output_device_names = {}

#for each audio device, determine if is an input or an output and add it to the appropriate list and dictionary
for i in range (0,numdevices):
    if p.get_device_info_by_host_api_device_index(0,i).get('maxInputChannels')>0:
        device_info = p.get_device_info_by_host_api_device_index(0,i)
        input_device_names[device_info["name"]] = device_info["index"]

    if p.get_device_info_by_host_api_device_index(0,i).get('maxOutputChannels')>0:
        device_info = p.get_device_info_by_host_api_device_index(0,i)
        output_device_names[device_info["name"]] = device_info["index"]

print("*** Input devices ***")
for name, index in input_device_names.items():
    print(f'{name}: {index}')
default_input_device_index = input_device_names.get("default")
if default_input_device_index:
    print(f'Default input device index is {default_input_device_index}')

print("\n*** Output devices ***")
for name, index in output_device_names.items():
    print(f'{name}: {index}')
default_output_device_index = output_device_names.get("default")
if default_output_device_index:
    print(f'Default output device index is {default_output_device_index}')

