'''
Timed Serial Decoder

A time and/or edge-based decoder for serial data without a clock reference.

This decoder captures serial bit streams by detecting edges and measuring time
intervals on a single data line.
It offers flexible (re-)synchronization options (rising, falling, or both edges) and
configurable sampling points.
Frame boundaries can be determined by pattern matching or time based idle data timeout.
Perfect for decoding custom or non-standard serial protocols that rely on defined
timing by absence of a clock signal.

Features:
 - Configurable bit rate and sample point
 - Edge-based start of frame synchronization (rising, falling, or both)
 - Optional re-synchronization on edge detection
 - Multiple EOF conditions: timeout, pattern match, or continuous
 - Frame-based output for stacked decoders
'''

from .pd import Decoder
