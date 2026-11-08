#!/usr/bin/env python3
"""Build the Loxone Config template for the Generic UDP controller.

The value names and decimals are read from the data_* tasks in
firmware/v0100/build/config.dat, so the template always matches the firmware.
The station sends one packet per value with the Controller Publish
%sysname%_%valname%=%value%, e.g. "weatherlox_temperature=20.34".

Usage:  python3 tools/build_loxone_template.py [--sysname weatherlox] [--port 7000]
Output: loxone/VIU_WeatherLox.xml (import in Loxone Config: Virtual UDP Input -> Import template)
"""
import argparse
import re
from pathlib import Path
from xml.sax.saxutils import quoteattr

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / 'firmware' / 'v0100' / 'build' / 'config.dat'
OUT = ROOT / 'loxone' / 'VIU_WeatherLox.xml'

# ExtraTaskSettingsStruct (ESPEasy mega): TaskIndex, TaskDeviceName[41], TaskDeviceFormula[4][41],
# TaskDeviceValueNames[4][41], dummy1, version, TaskDevicePluginConfigLong[16] (4-byte aligned),
# TaskDeviceValueDecimals[4]. Offsets relative to the start of the struct.
OFS_NAME, OFS_VALUENAMES, OFS_DECIMALS, LEN = 1, 206, 436, 41

# value name -> (title in Loxone, unit, note). Every value name in config.dat must be listed here.
VALUES = {
    # Air
    'temperature':           ('Außentemperatur', '°C', ''),
    'humidity':              ('Rel. Luftfeuchtigkeit', '%', ''),
    'dewpoint':              ('Taupunkt', '°C', ''),
    'feelslike':             ('Gefühlte Temperatur', '°C', ''),
    'heatindex':             ('Hitzeindex', '°C', ''),
    'windchill':             ('Windchill', '°C', ''),
    'humidity_abs':          ('Abs. Luftfeuchtigkeit', 'g/m³', ''),
    'vapourpressuredeficit': ('Sättigungsdefizit', 'hPa', ''),
    'cloudbase':             ('Wolkenuntergrenze', 'm', 'Cumulus'),
    'pressure_abs':          ('Luftdruck absolut', 'hPa', ''),
    'pressure_rel':          ('Luftdruck relativ', 'hPa', ''),
    'pressurechange1':       ('Änderung Luftdruck 1h', 'hPa', ''),
    'pressurechange3':       ('Änderung Luftdruck 3h', 'hPa', ''),
    'pressuretrend1':        ('Trend Luftdruck 1h', '', '-2 stark fallend, -1 fallend, 0 gleich, 1 steigend, 2 stark steigend'),
    'pressuretrend3':        ('Trend Luftdruck 3h', '', '-2 stark fallend, -1 fallend, 0 gleich, 1 steigend, 2 stark steigend'),
    # Rain / Rain Amount
    'rainstate':             ('Regenstatus', '', '0 trocken, 1 Regen/Schnee'),
    'rainrate':              ('Regenrate', 'mm/h', ''),
    'rain_event':            ('Regenmenge aktuelles Event', 'mm', ''),
    'rain_hourly':           ('Regenmenge aktuelle Stunde', 'mm', ''),
    'rain_daily':            ('Regenmenge aktueller Tag', 'mm', ''),
    'rain_weekly':           ('Regenmenge aktuelle Woche', 'mm', ''),
    'rain_monthly':          ('Regenmenge aktueller Monat', 'mm', ''),
    'rain_yearly':           ('Regenmenge aktuelles Jahr', 'mm', ''),
    'rain_24h':              ('Regenmenge letzte 24 h', 'mm', ''),
    # Windspeed / Winddirection
    'windspeed':             ('Windgeschwindigkeit', 'km/h', ''),
    'windspeed_avg2m':       ('Ø Windgeschwindigkeit 2 Min.', 'km/h', ''),
    'windspeed_avg10m':      ('Ø Windgeschwindigkeit 10 Min.', 'km/h', ''),
    'windgust_max2m':        ('Max. Windböe 2 Min.', 'km/h', ''),
    'windgust_max10m':       ('Max. Windböe 10 Min.', 'km/h', ''),
    'windgust_maxhourly':    ('Max. Windböe aktuelle Stunde', 'km/h', ''),
    'windgust_maxdaily':     ('Max. Windböe aktueller Tag', 'km/h', ''),
    'windgust_max24h':       ('Max. Windböe letzte 24 h', 'km/h', ''),
    'windrun_daily':         ('Windweg aktueller Tag', 'km', ''),
    'beaufort':              ('Windstärke', 'Bft', ''),
    'winddir':               ('Windrichtung', '°', ''),
    'winddir_avg2m':         ('Ø Windrichtung 2 Min.', '°', ''),
    'winddir_avg10m':        ('Ø Windrichtung 10 Min.', '°', ''),
    # Solar
    'illuminance':           ('Helligkeit', 'lx', ''),
    'solarradiation':        ('Solarstrahlung', 'W/m²', ''),
    'uvi':                   ('UV-Index', '', ''),
    'twilight':              ('Dämmerung', '%', ''),
    'sunshine':              ('Sonnenschein', '', '0 nein, 1 ja'),
    'solarradiation_daily':  ('Sonnenstrahlung aktueller Tag', 'Wh/m²', ''),
    'sunduration_daily':     ('Sonnenscheindauer aktueller Tag', 'h', ''),
    'sunelevation':          ('Sonnenhöhe', '°', ''),
    'sundirection':          ('Sonnenrichtung (Azimut)', '°', ''),
    # Lightning
    'lightning':             ('Entfernung letzter Blitz', 'km', ''),
    'lightning_daily':       ('Anzahl Blitze aktueller Tag', '', ''),
    'lightning_time':        ('Zeitpunkt letzter Blitz', '', 'Unix-Zeit (s seit 1.1.1970 UTC); Loxone-Zeit = Wert - 1230768000'),
    # Controller module: optional 1-Wire sensors
    'temperature1':          ('Temperatur 1 (1-Wire)', '°C', ''),
    'temperature2':          ('Temperatur 2 (1-Wire)', '°C', ''),
    'temperature3':          ('Temperatur 3 (1-Wire)', '°C', ''),
    'temperature4':          ('Temperatur 4 (1-Wire)', '°C', ''),
    # Open-Meteo (internet required)
    'weathercode':           ('Wettercode (WMO)', '', 'Open-Meteo'),
    'cloudcover':            ('Wolkendecke', '%', 'Open-Meteo'),
    'precipitationprob':     ('Regenwahrscheinlichkeit', '%', 'Open-Meteo'),
    'visibility':            ('Sichtweite', 'km', 'Open-Meteo'),
    'evapotranspiration':    ('Evapotranspiration', 'mm', 'Open-Meteo'),
    'et0evapotranspiration': ('Referenz-Evapotranspiration (ET0)', 'mm', 'Open-Meteo'),
}


def read_tasks(path):
    """Return [(task, [(valname, decimals), ...]), ...] of the data_* tasks, sorted by task number."""
    d = path.read_bytes()
    cstr = lambda b: b.split(b'\0')[0].decode('ascii')
    tasks = []
    for m in re.finditer(rb'data_(\d+)\x00', d):
        s = m.start() - OFS_NAME
        vals = []
        for k in range(4):
            name = cstr(d[s + OFS_VALUENAMES + k * LEN:s + OFS_VALUENAMES + (k + 1) * LEN])
            if name:
                vals.append((name, d[s + OFS_DECIMALS + k]))
        tasks.append((int(m.group(1)), vals))
    return sorted(tasks)


def build(sysname, port):
    crlf = '\r\n'
    lines = ['<?xml version="1.0" encoding="utf-8"?>',
             f'<VirtualInUdp Title="WeatherLox" Comment={quoteattr(f"Controller Publish: %sysname%_%valname%=%value%")} '
             f'Address="" Port="{port}">',
             '\t<Info templateType="1" minVersion="12020923"/>']
    missing, count = [], 0
    for task, vals in read_tasks(CONFIG):
        for name, dec in vals:
            if name not in VALUES:
                missing.append(f'data_{task}#{name}')
                continue
            title, unit, note = VALUES[name]
            comment = name + (f' - {note}' if note else '')
            fmt = f'<v.{dec}>' if dec else '<v>'
            lines.append('\t<VirtualInUdpCmd '
                         f'Title={quoteattr(title)} Comment={quoteattr(comment)} Address="" '
                         f'Check={quoteattr(f"{sysname}_{name}=" + chr(92) + "v")} '
                         'Signed="true" Analog="true" SourceValLow="0" DestValLow="0" SourceValHigh="100" '
                         'DestValHigh="100" DefVal="0" MinVal="-2147483647" MaxVal="2147483647" '
                         f'Unit={quoteattr(fmt + (" " + unit if unit else ""))} HintText=""/>')
            count += 1
    if missing:
        raise SystemExit('No title/unit in VALUES for: ' + ', '.join(missing))
    lines.append('</VirtualInUdp>')
    return crlf.join(lines) + crlf, count


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--sysname', default='weatherlox', help='Unit name of the station (%%sysname%%)')
    ap.add_argument('--port', default=7000, type=int, help='UDP port of the Miniserver')
    ap.add_argument('--out', default=OUT, type=Path)
    a = ap.parse_args()
    xml, count = build(a.sysname, a.port)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_bytes(b'\xef\xbb\xbf' + xml.encode('utf-8'))  # UTF-8 with BOM, CRLF, as Loxone Config writes it
    print(f'{a.out}: {count} values')


if __name__ == '__main__':
    main()
