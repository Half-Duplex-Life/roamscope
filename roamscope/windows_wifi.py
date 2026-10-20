"""Read-only Native Wi-Fi queries; no profiles, keys or Wi-Fi settings accessed.

Layouts follow Microsoft wlanapi.h. Only loaded on Windows. All buffers and
handles are released on success and failure. Returns diagnostics separately.
"""
import ctypes as C
import sys

D = C.c_uint32


class GUID(C.Structure):
    _fields_ = [('a', D), ('b', C.c_uint16), ('c', C.c_uint16),
                ('d', C.c_ubyte * 8)]


class Interface(C.Structure):
    _fields_ = [('guid', GUID), ('description', C.c_uint16 * 256), ('state', D)]


class SSID(C.Structure):
    _fields_ = [('length', D), ('data', C.c_ubyte * 32)]


class Association(C.Structure):
    _fields_ = [('ssid', SSID), ('bss_type', D), ('bssid', C.c_ubyte * 6),
                ('phy', D), ('phy_index', D), ('quality', D), ('rx', D), ('tx', D)]


class Connection(C.Structure):
    _fields_ = [('state', D), ('mode', D), ('profile', C.c_uint16 * 256),
                ('association', Association), ('security', D * 4)]


def decode_connection(conn):
    """Pure conversion, also exercised with synthetic ABI structures."""
    a = conn.association
    if conn.state != 1 or a.ssid.length > 32 or a.quality > 100:
        return None
    mac = bytes(a.bssid)
    if mac in (b'\x00' * 6, b'\xff' * 6) or mac[0] & 1:
        return None
    return dict(ssid=bytes(a.ssid.data[:a.ssid.length]).decode('utf-8', 'replace'),
                bssid=':'.join('%02x' % x for x in mac),
                rssi=round(a.quality / 2 - 100, 1), noise=None,
                tx_mbps=a.tx / 1000.0, phy='DOT11_PHY_TYPE %d' % a.phy)


def query_current():
    """Return (fields, diagnostic); refuse ambiguous multiple active adapters."""
    if sys.platform != 'win32':
        return None, 'Native Wi-Fi is available only on Windows.'
    dll = C.WinDLL('wlanapi.dll')
    P = C.c_void_p
    signatures = {
        'WlanOpenHandle': [D, P, C.POINTER(D), C.POINTER(P)],
        'WlanEnumInterfaces': [P, P, C.POINTER(P)],
        'WlanQueryInterface': [P, C.POINTER(GUID), D, P, C.POINTER(D), C.POINTER(P), P],
        'WlanCloseHandle': [P, P], 'WlanFreeMemory': [P],
    }
    for name, args in signatures.items():
        f = getattr(dll, name)
        f.argtypes, f.restype = args, (None if name == 'WlanFreeMemory' else D)
    handle, version, listing = P(), D(), P()
    code = dll.WlanOpenHandle(2, None, C.byref(version), C.byref(handle))
    if code:
        return None, 'WlanOpenHandle error %d' % code
    try:
        code = dll.WlanEnumInterfaces(handle, None, C.byref(listing))
        if code:
            return None, 'WlanEnumInterfaces error %d' % code
        count = C.cast(listing, C.POINTER(D))[0]
        if count > 64:
            return None, 'Unexpected Wi-Fi interface count.'
        found, errors = [], []
        for i in range(count):
            iface = Interface.from_address(listing.value + 8 + i * C.sizeof(Interface))
            if iface.state != 1:
                continue
            size, data = D(), P()
            code = dll.WlanQueryInterface(handle, C.byref(iface.guid), 7, None,
                                          C.byref(size), C.byref(data), None)
            try:
                if code:
                    errors.append('current connection error %d' % code)
                    continue
                if not data or size.value < C.sizeof(Connection):
                    errors.append('Truncated current connection response')
                    continue
                fields = decode_connection(C.cast(data, C.POINTER(Connection)).contents)
                if fields:
                    # Channel is queried on the SAME GUID; no cross-adapter merge.
                    ch_size, ch_data = D(), P()
                    ch_code = dll.WlanQueryInterface(handle, C.byref(iface.guid), 8, None,
                                                     C.byref(ch_size), C.byref(ch_data), None)
                    try:
                        if not ch_code and ch_data and ch_size.value >= 4:
                            fields['channel'] = C.cast(ch_data, C.POINTER(D))[0]
                    finally:
                        if ch_data:
                            dll.WlanFreeMemory(ch_data)
                    found.append(fields)
                else:
                    errors.append('Current connection has no valid BSSID')
            finally:
                if data:
                    dll.WlanFreeMemory(data)
        if len(found) == 1 and not errors:
            return found[0], 'Native Wi-Fi current connection'
        if len(found) > 1:
            return None, 'Multiple connected Wi-Fi adapters; use one adapter for this survey.'
        return None, '; '.join(errors) or 'No connected Wi-Fi interface.'
    finally:
        if listing:
            dll.WlanFreeMemory(listing)
        dll.WlanCloseHandle(handle, None)
