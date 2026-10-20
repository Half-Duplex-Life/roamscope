"""Synthetic regression tests. No production identifiers or captures."""
import ctypes
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from roamscope import collectors as c, report, store
from roamscope.roam import RoamTracker
from roamscope.windows_wifi import Connection, Association, decode_connection

MAC='02:11:22:33:44:55'
def output(label='BSSID', value=MAC):
    return f'Name : Wi-Fi\nState : connected\nSSID : Synthetic <test>\n\n {label} : {value}\nSignal : 84%\nChannel : 44\nBand : 5 GHz\nTransmit rate (Mbps) : 866.7\n'

class WindowsTests(unittest.TestCase):
    def test_legacy(self):
        s=c.parse_windows_interfaces(output());self.assertEqual(s['bssid'],MAC);self.assertEqual(s['rssi'],-58);self.assertEqual(s['freq_mhz'],5220)
    def test_ap_bssid(self):
        self.assertEqual(c.parse_windows_interfaces(output('AP BSSID'))['bssid'],MAC)
    def test_invalid_identity(self):
        for mac in ('00:00:00:00:00:00','ff:ff:ff:ff:ff:ff','n/a','01:11:22:33:44:55'):
            self.assertIsNone(c.parse_windows_interfaces(output(value=mac))['bssid'])
    def test_no_scan_guess(self):
        s=c.parse_windows_interfaces(output('Physical address'));self.assertIsNone(s['bssid'])
    def test_multiple_adapters(self):
        self.assertIsNone(c.parse_windows_interfaces(output()+output()))
    def test_disconnected(self):
        self.assertIsNone(c.parse_windows_interfaces(output().replace('connected','disconnected')))
    def test_localized_is_not_guessed(self):
        self.assertIsNone(c.parse_windows_interfaces('Name : WLAN\nStatus : Verbunden\nBSSID : '+MAC))
    def test_band_ambiguity(self):
        self.assertIsNone(c.parse_windows_interfaces(output().replace('Band : 5 GHz\n',''))['freq_mhz'])
    def test_doctor_missing_bssid(self):
        with patch.object(c,'collect_windows',return_value=(c.parse_windows_interfaces(output('Physical address')),None)):
            self.assertFalse(c.diagnose_windows()[0])
    def test_native_layout_and_decode(self):
        self.assertEqual(ctypes.sizeof(Association),68);self.assertEqual(ctypes.sizeof(Connection),604)
        con=Connection();con.state=1;con.association.ssid.length=4;con.association.ssid.data[:4]=b'Test';con.association.bssid[:]=bytes.fromhex(MAC.replace(':',''));con.association.quality=84;con.association.tx=866700
        self.assertEqual(decode_connection(con)['bssid'],MAC);self.assertEqual(decode_connection(con)['tx_mbps'],866.7)
        con.association.ssid.length=33;self.assertIsNone(decode_connection(con))
    def test_native_preferred_and_same_ap_merge(self):
        native=dict(bssid=MAC,ssid='Test',rssi=-58)
        with patch('roamscope.windows_wifi.query_current',return_value=(native,'Native Wi-Fi')),patch.object(c,'run',return_value=output()):
            s,_=c.collect_windows();self.assertEqual(s['freq_mhz'],5220)
        with patch('roamscope.windows_wifi.query_current',return_value=(native,'Native Wi-Fi')),patch.object(c,'run',return_value=output(value='02:11:22:33:44:66')):
            s,_=c.collect_windows();self.assertIsNone(s['freq_mhz'])
    def test_native_denied_fallback(self):
        with patch('roamscope.windows_wifi.query_current',return_value=(None,'error 5')),patch.object(c,'run',return_value=output('AP BSSID')):
            self.assertEqual(c.collect_windows()[0]['bssid'],MAC)
    def test_native_multiple_refused(self):
        with patch('roamscope.windows_wifi.query_current',return_value=(None,'Multiple connected Wi-Fi adapters')),patch.object(c,'run') as run:
            self.assertIsNone(c.collect_windows()[0]);run.assert_not_called()

class ReportTests(unittest.TestCase):
    def build(self, identities, dest=None):
        if dest is None:
            tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
            self.addCleanup(tmp.cleanup)
            folder=Path(tmp.name)
        else:
            folder=Path(dest)
        folder.mkdir(parents=True,exist_ok=True)
        db=store.open_db(str(folder/'test.sqlite'));store.set_meta(db,'platform','windows');store.set_meta(db,'started','SYNTHETIC TEST')
        tracker=RoamTracker()
        for i,b in enumerate(identities):
            s=dict(ts_epoch=1700000000+i*2,ssid='<script>alert(1)</script>',bssid=b,rssi=-58-i%4,noise=None,channel=44,freq_mhz=5220,platform='windows')
            store.insert_sample(db,s);ev=tracker.feed(s,[])
            if ev:store.insert_roam(db,ev)
        stats=report.compute_stats(db)[0];db.close()
        report.build_report(str(folder/'test.sqlite'),str(folder/'report.html'))
        return (folder/'report.html').read_text(encoding='utf-8'),stats
    def test_missing_bssid_153_samples(self):
        html,stats=self.build([None]*153)
        self.assertEqual(stats['n_samples'],153);self.assertIn('0 of 153',html);self.assertIn('Unavailable',html)
        self.assertIn('No associated AP identity',html);self.assertNotIn('<script>alert',html)
        self.assertIn('data:image/',html)
    def test_stationary(self):
        html,stats=self.build([MAC]*12);self.assertEqual(stats['n_roams'],0);self.assertEqual(len(stats['ap_rows']),1);self.assertIn('&lt;script&gt;',html)
    def test_roaming(self):
        html,stats=self.build([MAC]*3+['02:11:22:33:44:66']*3);self.assertEqual(stats['n_roams'],1);self.assertIn('R1',html)
    def test_empty(self):
        html,stats=self.build([]);self.assertIn('No observed transitions',html);self.assertEqual(stats['n_samples'],0)

if __name__=='__main__':unittest.main()

