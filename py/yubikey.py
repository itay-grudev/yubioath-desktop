#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import types
import re
from base64 import b32decode, b64decode
from binascii import a2b_hex, b2a_hex

from ykman.descriptor import get_descriptors
from ykman.util import CAPABILITY, TRANSPORT, derive_key, parse_uri
from ykman.oath import OathController, Credential
from py.qr import qrparse
from py.qr import qrdecode

NON_FEATURE_CAPABILITIES = [CAPABILITY.CCID, CAPABILITY.NFC]


def as_json(f):
    def wrapped(*args):
        return json.dumps(f(*(json.loads(a) for a in args)))
    return wrapped


class Controller(object):
    _descriptor = None
    _dev_info = None

    def __init__(self):
        # Wrap all args and return values as JSON.
        for f in dir(self):
            if not f.startswith('_'):
                func = getattr(self, f)
                if isinstance(func, types.MethodType):
                    setattr(self, f, as_json(func))

    def get_features(self):
        return [c.name for c in CAPABILITY if c not in NON_FEATURE_CAPABILITIES]

    def count_devices(self):
        return len(list(get_descriptors()))

    def refresh(self):
        descriptors = list(get_descriptors())
        if len(descriptors) != 1:
            self._descriptor = None
            return

        desc = descriptors[0]
        if desc.fingerprint != (self._descriptor.fingerprint if self._descriptor else None):
            dev = desc.open_device()
            if not dev:
                return
            self._descriptor = desc
            self._dev_info = {
                'name': dev.device_name,
                'version': '.'.join(str(x) for x in dev.version),
                'serial': dev.serial or '',
                'enabled': [c.name for c in CAPABILITY if c & dev.enabled],
                'connections': [t.name for t in TRANSPORT if t & dev.capabilities],
            }

        return self._dev_info

    def refresh_credentials(self, timestamp, password_key=None):
        if password_key is not None:
            password_key = a2b_hex(password_key)
        return [c.to_dict() for c in self._calculate_all(timestamp, password_key)]

    def calculate(self, credential, timestamp, password_key):
        return self._calculate(Credential.from_dict(credential), timestamp, password_key).to_dict()

    def needs_validation(self):
        dev = self._descriptor.open_device(TRANSPORT.CCID)
        controller = OathController(dev.driver)
        return controller.locked

    def validate(self, password):
        dev = self._descriptor.open_device(TRANSPORT.CCID)
        controller = OathController(dev.driver)
        key = derive_key(controller.id, password)
        try:
            controller.validate(key)
            return b2a_hex(key).decode('utf-8')
        except:
            return False

    def set_password(self, new_password, password_key):
        dev = self._descriptor.open_device(TRANSPORT.CCID)
        controller = OathController(dev.driver)
        if controller.locked and password_key is not None:
            controller.validate(a2b_hex(password_key))
        if new_password is not None:
            key = derive_key(controller.id, new_password)
            controller.set_password(key)
        else:
            controller.clear_password()

    def add_credential(self, name, key, oath_type, digits, algo, touch, password_key):
        dev = self._descriptor.open_device(TRANSPORT.CCID)
        controller = OathController(dev.driver)
        if controller.locked and password_key is not None:
            controller.validate(a2b_hex(password_key))
        try:
            key = self._parse_key(key)
        except Exception as e:
            return str(e)
        controller.put(key, name, oath_type, digits, algo=algo, require_touch=touch)


    def delete_credential(self, credential, password_key):
        dev = self._descriptor.open_device(TRANSPORT.CCID)
        controller = OathController(dev.driver)
        if controller.locked and password_key is not None:
            controller.validate(a2b_hex(password_key))
        controller.delete(Credential.from_dict(credential))

    def _calculate(self, credential, timestamp, password_key):
        dev = self._descriptor.open_device(TRANSPORT.CCID)
        controller = OathController(dev.driver)
        if controller.locked and password_key is not None:
            controller.validate(password_key)
        cred = controller.calculate(credential, timestamp)
        return cred

    def _calculate_all(self, timestamp, password_key):
        dev = self._descriptor.open_device(TRANSPORT.CCID)
        controller = OathController(dev.driver)

        if controller.locked and password_key is not None:
            controller.validate(password_key)
        creds = controller.calculate_all(timestamp)
        creds = [c for c in creds if not c.hidden]
        return creds

    def _parse_key(self, val):
        val = val.upper()
        if re.match(r'^([0-9A-F]{2})+$', val):  # hex
            return a2b_hex(val)
        else:
            # Key should be b32 encoded
            return self._parse_b32_key(val)

    def _parse_b32_key(self, key):
        key += '=' * (-len(key) % 8)  # Support unpadded
        return b32decode(key)


    def parse_qr(self, screenshots):
        for s in screenshots:
            data = b64decode(s['data'])
            image = PixelImage(data, s['width'], s['height'])
            for qr in qrparse.parse_qr_codes(image, 2):
                return parse_uri(qrdecode.decode_qr_data(qr))


class PixelImage(object):

    def __init__(self, data, width, height):
        self.data = data
        self.width = width
        self.height = height

    def get_line(self, line_number):
        return self.data[self.width * line_number:self.width * (line_number + 1)]

controller = Controller()
