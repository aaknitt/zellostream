from pulseaudio import PulseAudioHandler

pulse = PulseAudioHandler()

print("Sources:")
for source_name, source_index in pulse.list_sources().items():
    print(f'{source_index}: {source_name}')

print("\nSinks:")
for sink_name, sink_index in pulse.list_sinks().items():
    print(f'{sink_index}: {sink_name}')
