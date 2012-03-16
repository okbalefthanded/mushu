#!/usb/bin/env python


import struct
import time
from exceptions import Exception
import logging

import usb
from scipy.signal import iirfilter
import amplifier


logger = logging.getLogger(__name__)
logger.info('Logger started')

ID_VENDOR_GTEC = 0x153c
ID_PRODUCT_GUSB_AMP = 0x0001

CX_OUT = usb.TYPE_VENDOR | usb.ENDPOINT_OUT



class GTecAmp(amplifier.Amplifier):

    def __init__(self):
        logger.info('Initializing GTecAmp instance')
        # list of available amps
        self.amps = []
        for bus in usb.busses():
            for device in bus.devices:
                if (device.idVendor == ID_VENDOR_GTEC and
                    device.idProduct == ID_PRODUCT_GUSB_AMP):
                    self.amps.append(device)
        self.connected = False
        self.devh = None

    def start(self):
        """Initialize the amplifier and make it ready."""
        device = self.amps[0]
        self.devh = device.open()
        # detach kernel driver if nessecairy
        config = device.configurations[0]
        self.devh.setConfiguration(config)
        assert(len(config.interfaces) > 0)
        first_interface = config.interfaces[0][1]
        first_setting = first_interface.alternateSetting
        self.devh.claimInterface(first_interface)
        self.devh.setAltInterface(first_interface)
        # initialization straight from the usb-dump
        self.set_mode('data')
        self.devh.controlMsg(CX_OUT, 0xb6, value=0x80, buffer=0)
        self.devh.controlMsg(CX_OUT, 0xb5, value=0x80, buffer=0)
        self.devh.controlMsg(CX_OUT, 0xb9, value=0x00, buffer="\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10")
        self.devh.controlMsg(CX_OUT, 0xcd, value=0x00, buffer=0)
        self.devh.controlMsg(CX_OUT, 0xd3, value=0x01, buffer=0)
        self.devh.controlMsg(CX_OUT, 0xca, value=0x01, buffer=0)
        self.devh.controlMsg(CX_OUT, 0xc8, value=0x01, buffer="\x00"*16)
        self.devh.controlMsg(CX_OUT, 0xbf, value=0x00, buffer=0)
        self.devh.controlMsg(CX_OUT, 0xbe, value=0x00, buffer=0)
        self.set_calibration_mode('sine')
        self.set_sampling_ferquency(128, [False for i in range(16)], None, None)

    def start_recording(self):
        self.devh.controlMsg(CX_OUT, 0xb5, value=0x08, buffer=0)
        self.devh.controlMsg(CX_OUT, 0xf7, value=0x00, buffer=0)

    def stop_recording(self):
        """Shut down the amplifier."""
        self.devh.controlMsg(CX_OUT, 0xb8, [])

    def get_data(self):
        """Get data."""
        # TODO: what is the in-endpoint
        # 0x2 or 0x86
        endpoint = 0x86
        size = 512
        data = self.devh.bulkRead(endpoint, size)
        data = ''.join([chr(i) for i in data])
        data = struct.unpack_from('<'+'f'*(len(data)/4), data)
        return data

    def get_impedances(self):
        """Get the impedances."""
        pass

    def set_mode(self, mode):
        """Set mode, 'impedance', 'data'."""
        if mode == 'impedance':
            self.devh.controlMsg(CX_OUT, 0xc9, value=0x00, buffer=0)
            self.devh.controlMsg(CX_OUT, 0xc2, value=0x03, buffer=0)
        elif mode == 'calibrate':
            self.devh.controlMsg(CX_OUT, 0xc1, value=0x00, buffer=0)
            self.devh.controlMsg(CX_OUT, 0xc2, value=0x02, buffer=0)
        elif mode == 'data':
            self.devh.controlMsg(CX_OUT, 0xc0, value=0x00, buffer=0)
            self.devh.controlMsg(CX_OUT, 0xc2, value=0x01, buffer=0)
        else:
            raise AmpError('Unknown mode: %s' % mode)


    def set_sampling_ferquency(self, fs, channels, bpfilter, notchfilter):
        """ Set the sampling frequency and filters for individual channels.

        Parameters:
        fs -- sampling frequency
        channels -- list of booleans: channels[0] == True: enable filter for channel 0
        bpfilter -- tuple: parameters for the band pass filter (hp, lp, fs, order) or None
        notchfilter -- tuple: parameters for the band stop filter (hp, lp, fs, order) or None

        """
        # we have: hp, lp, fs, order, typ
        # signal.iirfilter(order/2, [hp/(fs/2), lp/(fs/2)], ftype='butter', btype='band')
        # we get 18 coeffs and put them in as '<d' in the buffer
        # struct.pack('<'+'d'*18, *coeffs)

        # special filter: means no filter
        null_filter = "\x00\x00\x00\x00\x00\x00\xf0\x3f"+"\x00\x00\x00\x00\x00\x00\x00\x00"*17

        if bpfilter:
            bp_hp, bp_lp, bp_fs, bp_order = bpfilter
            bp_b, bp_a = iirfilter(bp_order/2, [bp_hp/(bp_fs/2), bp_lp/(bp_fs/2)], ftype='butter', btype='band')
            bp_filter = list(bp_b)
            bp_filter.extend(list(bp_a))
            bp_filter = struct.pack("<"+"d"*18, *bp_filter)
        else:
            bp_filter = null_filter

        if notchfilter:
            bs_hp, bs_lp, bs_fs, bs_order = notchfilter
            bs_b, bs_a = iirfilter(bs_order/2, [bs_hp/(bs_fs/2), bs_lp/(bs_fs/2)], ftype='butter', btype='bandstop')
            bs_filter = list(bs_b)
            bs_filter.extend(list(bs_a))
            bs_filter = struct.pack("<"+"d"*18, *bs_filter)
        else:
            bs_filter = null_filter

        # set the filters for all channels
        if bpfilter == notchfilter == None:
            self.devh.controlMsg(CX_OUT, 0xc6, value=0x01, buffer=bp_filter)
            self.devh.controlMsg(CX_OUT, 0xc7, value=0x01, buffer=bs_filter)
        else:
            idx = 1
            for i in channels:
                if i:
                    self.devh.controlMsg(CX_OUT, 0xc6, value=idx, buffer=bp_filter)
                    self.devh.controlMsg(CX_OUT, 0xc7, value=idx, buffer=bs_filter)
                idx += 1

        # set the sampling frequency
        self.devh.controlMsg(CX_OUT, 0xb6, value=fs, buffer=0)


    def set_calibration_mode(self, mode):
        # buffer: [0x03, 0xd0, 0x07, 0x02, 0x00, 0xff, 0x07]
        #          ====  ==========
        # (1) mode:
        # (2) amplitude: little endian (0x07d0 = 2000)
        if mode == 'sine':
            self.devh.controlMsg(CX_OUT, 0xcb, value=0x00, buffer="\x03\xd0\x07\x02\x00\xff\x07")
        elif mode == 'sawtooth':
            self.devh.controlMsg(CX_OUT, 0xcb, value=0x00, buffer="\x02\xd0\x07\x02\x00\xff\x07")
        elif mode == 'whitenoise':
            self.devh.controlMsg(CX_OUT, 0xcb, value=0x00, buffer="\x05\xd0\x07\x02\x00\xff\x07")
        elif mode == 'square':
            self.devh.controlMsg(CX_OUT, 0xcb, value=0x00, buffer="\x01\xd0\x07\x02\x00\xff\x07")
        else:
            raise AmpError('Unknown mode: %s' % mode)

    def calculate_impedance(self, u_measured, u_applied):
        return (u_measured * 1e6) / (u_applied - u_measured) - 1e4


class AmpError(Exception):
    pass


if __name__ == '__main__':
    amp = GTecAmp()
    amp.start()
    try:
        while True:
            t = time.time()
            data = amp.get_data()
            dt = time.time() - t
            if len(data) > 0:
                print "%.5f seconds (%.5f ps), length: %d" % (dt, (len(data) / 16.) * 1/dt, len(data))
    finally:
        amp.stop()

