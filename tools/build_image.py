#!/usr/bin/env python3
"""Builds a complete WeatherLox flash image (firmware + preconfigured file system).

The ESPEasy build only creates bootloader, partition table and program (.factory.bin).
This script adds a LittleFS file system with the WeatherLox configuration from
firmware/v0100/build and merges both into one file that is flashed at address 0x0:

  config.dat, rules1.txt ... rules4.txt, json.keys, provisioning.dat  (from the build folder)
  security.dat  (generated: no WiFi, AP key / admin password / IP block level from Custom.h)

Usage:
  pip install littlefs-python
  python tools/build_image.py <firmware.factory.bin> [-o <output.bin>]

The output contains no personal data: security.dat is generated from Custom.h and the
image is checked for an empty WiFi configuration before it is written.
"""
import argparse
import re
import struct
import sys
from pathlib import Path

from littlefs import LittleFS

REPO = Path(__file__).resolve().parent.parent
BUILD = REPO / 'firmware' / 'v0100' / 'build'
FILES = ['config.dat', 'rules1.txt', 'rules2.txt', 'rules3.txt', 'rules4.txt', 'json.keys', 'provisioning.dat']

# LittleFS parameters of ESPEasy on ESP32 (arduino-esp32 / esp_littlefs defaults)
LFS_BLOCK_SIZE = 4096
LFS_READ_PROG_SIZE = 128
LFS_NAME_MAX = 64
LFS_DISK_VERSION = 0x00020000  # littlefs 2.0, mountable by all esp_littlefs versions

# SecurityStruct (ESPEasy src/src/DataStructs/SecurityStruct.h, ESP32: CONTROLLER_MAX = 3)
SEC_SIZE = 4096
SEC_WIFI_END = 192     # WifiSSID, WifiKey, WifiSSID2, WifiKey2
SEC_AP_KEY = (192, 64)
SEC_PASSWORD = (526, 26)
SEC_IP_BLOCK_LEVEL = 560


def die(msg):
    sys.exit(f'Error: {msg}')


def partitions(image):
    """Partition table at 0x8000: list of (name, type, subtype, offset, size)."""
    result = []
    for pos in range(0x8000, 0x8000 + 0xC00, 32):
        entry = image[pos:pos + 32]
        if entry[:2] != b'\xaa\x50':
            break
        offset, size = struct.unpack('<II', entry[4:12])
        result.append((entry[12:28].rstrip(b'\0').decode(), entry[2], entry[3], offset, size))
    return result


def custom_h_define(text, name):
    m = re.search(r'^\s*#define\s+' + name + r'\s+("([^"]*)"|(\d+))', text, re.M)
    if not m:
        die(f'{name} not found in Custom.h')
    return m.group(2) if m.group(2) is not None else int(m.group(3))


def security_dat():
    text = (BUILD / 'Custom.h').read_text(encoding='utf-8', errors='replace')
    data = bytearray(SEC_SIZE)
    for (offset, length), value in ((SEC_AP_KEY, custom_h_define(text, 'DEFAULT_AP_KEY')),
                                    (SEC_PASSWORD, custom_h_define(text, 'DEFAULT_ADMIN_PASS'))):
        raw = value.encode()
        if len(raw) >= length:
            die(f'value too long for security.dat: {value}')
        data[offset:offset + len(raw)] = raw
    data[SEC_IP_BLOCK_LEVEL] = custom_h_define(text, 'DEFAULT_IP_BLOCK_LEVEL')
    return bytes(data)


def littlefs_image(files, size):
    fs = LittleFS(block_size=LFS_BLOCK_SIZE, block_count=size // LFS_BLOCK_SIZE,
                  read_size=LFS_READ_PROG_SIZE, prog_size=LFS_READ_PROG_SIZE,
                  name_max=LFS_NAME_MAX, disk_version=LFS_DISK_VERSION)
    for name, content in files.items():
        with fs.open(name, 'wb') as f:
            f.write(content)
    image = bytes(fs.context.buffer)
    if len(image) != size:
        die(f'LittleFS image has {len(image)} bytes instead of {size}')
    return image


def verify(image, size, files):
    fs = LittleFS(block_size=LFS_BLOCK_SIZE, block_count=size // LFS_BLOCK_SIZE,
                  read_size=LFS_READ_PROG_SIZE, prog_size=LFS_READ_PROG_SIZE,
                  name_max=LFS_NAME_MAX, mount=False)
    fs.context.buffer[:] = image
    fs.mount()
    if sorted(fs.listdir('/')) != sorted(files):
        die(f'file list differs: {sorted(fs.listdir("/"))}')
    for name, content in files.items():
        with fs.open(name, 'rb') as f:
            if f.read() != content:
                die(f'{name} differs after reading back')
    sec = files['security.dat']
    if any(sec[:SEC_WIFI_END]) or any(sec[SEC_PASSWORD[0] + SEC_PASSWORD[1]:SEC_IP_BLOCK_LEVEL]) \
            or any(sec[SEC_IP_BLOCK_LEVEL + 1:]):
        die('security.dat contains WiFi data, IP range or controller credentials')
    prov = files['provisioning.dat']
    if any(prov[36:126]):
        die('provisioning.dat contains user or password')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('factory', type=Path, help='firmware .factory.bin from the ESPEasy build')
    ap.add_argument('-o', '--output', type=Path, help='output file (default: <factory>_full.bin)')
    args = ap.parse_args()

    factory = args.factory.read_bytes()
    parts = partitions(factory)
    fs_parts = [p for p in parts if p[1] == 1 and p[2] in (0x82, 0x83)]  # data: spiffs / littlefs
    if len(fs_parts) != 1:
        die(f'no unique file system partition found: {parts}')
    name, _, _, fs_offset, fs_size = fs_parts[0]
    if len(factory) > fs_offset:
        die('factory image overlaps the file system partition')

    files = {f: (BUILD / f).read_bytes() for f in FILES}
    files['security.dat'] = security_dat()

    fs_image = littlefs_image(files, fs_size)
    verify(fs_image, fs_size, files)

    out = bytearray(b'\xff' * (fs_offset + fs_size))
    out[:len(factory)] = factory
    out[fs_offset:] = fs_image

    output = args.output or args.factory.with_name(args.factory.name.replace('.factory.bin', '') + '_full.bin')
    output.write_bytes(out)
    print(f'{output}: {len(out)} bytes, file system "{name}" at 0x{fs_offset:X} ({fs_size // 1024} KB): '
          + ', '.join(sorted(files)))


if __name__ == '__main__':
    main()
