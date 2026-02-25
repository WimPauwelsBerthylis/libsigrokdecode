import sigrokdecode as srd

'''
OUTPUT_PYTHON format:

Packet:
[<ptype>, <pdata>]

<ptype>:
 - 'BIT': Single bit value
 - 'FRAME': Complete frame data

<pdata>:
 - For 'BIT': Integer (0 or 1) representing the bit value
 - For 'FRAME': List of integers representing all bits in the frame
'''

class Ann:
    SAMPLEPOINTS, BITS, STATES = range(3)

class SamplerateError(Exception):
    pass

class Decoder(srd.Decoder):
    api_version = 3
    id = 'timed_serial'
    name = 'Timed Serial'
    longname = 'Timed Serial Decoder'
    desc = 'Timed serial bit stream decoding.'
    license = 'gplv2+'
    inputs = ['logic']
    outputs = ['timed_serial']
    tags = ['Embedded/industrial']
    channels = (
        {'id': 'data', 'name': 'DATA', 'desc': 'Serial data line'},
    )
    options = (
        {'id': 'bitrate', 'desc': 'Bitrate (bps)', 'default': 500000},
        {'id': 'sync_edge', 'desc': 'Synchronization edge', 'default': 'Rising', 'values': ('Rising', 'Falling', 'Both')},
        {'id': 'sample_point', 'desc': 'Sample Point (%)', 'default': 50},
        {'id': 'resync', 'desc': 'Re-synchronise', 'default': 'True', 'values': ('True', 'False')},
        {'id': 'eof_condition', 'desc': 'End of Frame Condition', 'default': 'Pattern', 'values': ('None', 'Timeout', 'Pattern')},
        {'id': 'eof_time', 'desc': 'End of Frame Time (us)', 'default': 0},
        {'id': 'eof_pattern', 'desc': 'End of Frame Pattern', 'default': '[0,0,0,0]'},
    )
    annotations = (
        ('sample', 'Sample'),
        ('bit', 'Bit'),
        ('state', 'State'),
    )
    annotation_rows = (
        ('samplepoints', 'Sample Points', (Ann.SAMPLEPOINTS,)),
        ('bits', 'Bits', (Ann.BITS,)),
        ('states', 'States', (Ann.STATES,)),
    )

    def __init__(self):
        self.reset()

    def reset(self):
        self.state = 'IDLE'
        self.buf = []
        self.es = 0
        self.frame_start = None
        self.last_dout = 0
        self.timeout_counter = 0

    def start(self):
        self.out_ann = self.register(srd.OUTPUT_ANN)
        self.out_python = self.register(srd.OUTPUT_PYTHON)

    def metadata(self, key, value):
        if key == srd.SRD_CONF_SAMPLERATE:
            self.samplerate = value
            # The width of one bit in number of samples.
            self.bit_time = float(self.samplerate) / float(self.options['bitrate'])
            # Convert eof_time from microseconds to samples
            eof_time_us = float(self.options['eof_time'])
            self.eof_time_samples = max(1, eof_time_us * self.samplerate / 1e6)

    def get_sync_edge(self):
        '''Return the sync edge condition based on options.'''
        sync_edge = self.options['sync_edge']
        if sync_edge == 'Rising':
            return {0: 'r'}
        elif sync_edge == 'Falling':
            return {0: 'f'}
        elif sync_edge == 'Both':
            return {0: 'e'}
        return {0: 'r'}  # Default to rising

    def parse_eof_pattern(self):
        '''Parse the EOF pattern string into a list of integers.'''
        pattern_str = self.options['eof_pattern']
        try:
            # Convert string representation like '[0,0,0,0]' to list
            pattern = eval(pattern_str)
            if isinstance(pattern, list):
                return pattern
        except Exception:
            pass
        return [0, 0, 0, 0]  # Default pattern

    def check_eof_condition(self):
        '''Check if end of frame condition is met.'''
        eof_condition = self.options['eof_condition']
        if eof_condition == 'None':
            return False
        elif eof_condition == 'Pattern':
            pattern = self.parse_eof_pattern()
            if (len(self.buf) >= len(pattern)) and (self.buf[-len(pattern):] == pattern):
                return True
        elif eof_condition == 'Timeout':
            # Convert eof_time from seconds to samples
            if self.timeout_counter >= self.eof_time_samples:
                return True
        return False

    def emit_sample(self, dout):
        '''Emit sample annotations and update state.'''
        self.buf.append(dout[0])
        self.put(self.samplenum, self.samplenum, self.out_ann, [Ann.SAMPLEPOINTS, ['.']])
        self.put(self.es, self.samplenum, self.out_ann, [Ann.STATES, [self.state]])
        self.put(self.es, self.samplenum, self.out_ann, [Ann.BITS, ['%d' % self.last_dout]])
        self.put(self.samplenum, self.samplenum, self.out_python, ['BIT', dout[0]])
        self.last_dout = dout[0]
        self.es = self.samplenum

    def handle_idle_state(self, sync_edge):
        '''Handle IDLE state: wait for sync edge.'''
        dout = self.wait(sync_edge)
        self.emit_sample(dout)
        self.state = 'SYNC'
        self.frame_start = self.samplenum
        self.timeout_counter = 0

    def handle_sync_state(self, sample_point):
        '''Handle SYNC state: wait for first data bit.'''
        dout = self.wait({'skip': int(self.bit_time * (1.0 + sample_point))})
        self.emit_sample(dout)
        self.state = 'DATA'
        # self.frame_start = self.samplenum
        self.timeout_counter = 0

        if self.check_eof_condition():
            self.put(self.frame_start, self.samplenum, self.out_python, ['FRAME', self.buf.copy()])
            self.buf = []
            self.state = 'IDLE'

    def handle_data_state(self, sync_edge, resync_enabled):
        '''Handle DATA state: receive data bits.'''
        if resync_enabled:
            dout = self.wait([sync_edge, {'skip': int(self.bit_time)}])
            if self.matched[0]:
                self.state = 'SYNC'
        else:
            dout = self.wait({'skip': int(self.bit_time)})
        self.emit_sample(dout)

        if dout[0] != self.last_dout:
            self.timeout_counter = 0
        else:
            self.timeout_counter += int(self.bit_time)

        if self.check_eof_condition():
            self.put(self.frame_start, self.samplenum, self.out_python, ['FRAME', self.buf.copy()])
            self.buf = []
            self.state = 'IDLE'

    def decode(self):
        sync_edge = self.get_sync_edge()
        resync_enabled = self.options['resync'] == 'True'
        sample_point = float(self.options['sample_point']) / 100.0

        if not self.samplerate:
            raise SamplerateError('Cannot decode without samplerate.')

        if self.bit_time <= 1:
            raise SamplerateError('Increase sample rate, too slow for selected bit rate.')

        if sample_point < 0 or sample_point > 1:
            raise SamplerateError('Sample point out of range: %.2f%% (should be 0-100%%)' % (sample_point * 100))

        while True:
            if self.state == 'IDLE':
                self.handle_idle_state(sync_edge)
            elif self.state == 'SYNC':
                self.handle_sync_state(sample_point)
            elif self.state == 'DATA':
                self.handle_data_state(sync_edge, resync_enabled)
