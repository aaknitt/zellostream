import pulsectl
import os

class PulseAudioHandler:
    def __init__(self):
        self._pulse = pulsectl.Pulse('zello-pulseaudio')

    def list_sources(self):
        result = {}
        pulse_sources = self._pulse.source_list()
        for pulse_source in pulse_sources:
            result[pulse_source.name] = pulse_source.index
        return result

    def list_sinks(self):
        result = {}
        pulse_sinks = self._pulse.sink_list()
        for pulse_sink in pulse_sinks:
            result[pulse_sink.name] = pulse_sink.index
        return result

    def get_source_index(self, pulse_name):
        pulse_sources = self._pulse.source_list()
        for pulse_source in pulse_sources:
            if pulse_source.name == pulse_name:
                return pulse_source.index
        return None

    def get_sink_index(self, pulse_name):
        pulse_sinks = self._pulse.sink_list()
        for pulse_sink in pulse_sinks:
            if pulse_sink.name == pulse_name:
                return pulse_sink.index
        return None

    def get_own_sink_input_index(self):
        pulse_sink_inputs = self._pulse.sink_input_list()
        for pulse_sink_input in pulse_sink_inputs:
            pid = int(pulse_sink_input.proplist.get("application.process.id"))
            if pid == os.getpid():
                return pulse_sink_input.index
        return None

    def get_own_source_output_index(self):
        pulse_source_outputs = self._pulse.source_output_list()
        for pulse_source_output in pulse_source_outputs:
            pid = int(pulse_source_output.proplist.get("application.process.id"))
            if pid == os.getpid():
                return pulse_source_output.index
        return None

    def move_sink_input(self, sink_input_index, sink_index):
        try:
            self._pulse.sink_input_move(sink_input_index, sink_index)
        except Exception as ex:
            print(f'PulseAudioHandler.move_sink_input: cannot move sink input: {ex}')

    def move_source_output(self, source_output_index, source_index):
        try:
            self._pulse.source_output_move(source_output_index, source_index)
        except Exception as ex:
            print(f'PulseAudioHandler.move_source_output: cannot move source output: {ex}')
