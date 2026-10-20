"""Dependency-free charts for installations without Matplotlib.

SVG is embedded as a data URL in the same self-contained HTML report.
"""
import base64
from html import escape


def _svg(title, body):
    text = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 280">'
            '<rect width="1000" height="280" fill="#14171c"/>'
            '<text x="35" y="30" fill="white" font-size="18">%s</text>%s</svg>'
            % (escape(title), body))
    return base64.b64encode(text.encode()).decode()


def _empty(title, msg='No measurements available'):
    return _svg(title, '<text x="40" y="130" fill="#bbb">%s</text>' % escape(msg))


def _line(title, samples, value):
    pts = [(s['ts_epoch'], value(s)) for s in samples if value(s) is not None]
    if not pts:
        return _empty(title)
    t0, t1 = min(t for t, _ in pts), max(t for t, _ in pts)
    lo, hi = min(v for _, v in pts) - 2, max(v for _, v in pts) + 2
    coords = [(65 + (t-t0)/max(1,t1-t0)*890, 225-(v-lo)/(hi-lo)*165) for t,v in pts]
    body = '<path d="M65 55 V225 H960" fill="none" stroke="#aaa"/>'
    body += '<polyline points="%s" fill="none" stroke="#73bdff" stroke-width="2"/>' % ' '.join('%.1f,%.1f'%p for p in coords)
    body += ''.join('<circle cx="%.1f" cy="%.1f" r="2" fill="#73bdff"/>' % p for p in coords)
    body += '<text x="5" y="65" fill="#ccc">%.1f</text><text x="5" y="225" fill="#ccc">%.1f</text>' % (hi,lo)
    body += '<text x="65" y="255" fill="#ccc">0 seconds</text><text x="830" y="255" fill="#ccc">%.1f seconds</text>' % (t1-t0)
    return _svg(title, body)


def rssi_plot(samples, roams, ap_names=None):
    return _line('RSSI (dBm); sampled time', samples, lambda s:s.get('rssi'))


def snr_plot(samples, roams, ap_names=None):
    return _line('SNR (dB)', samples, lambda s: s['rssi']-s['noise'] if s.get('rssi') is not None and s.get('noise') is not None else None)


def _bars(title, values):
    if not values:
        return _empty(title)
    # Limit chart density; complete values remain in the event/AP tables.
    values = values[:20]
    scale = max(abs(v) for _,v in values) or 1
    step = 180/len(values)
    body = ''
    for i,(label,v) in enumerate(values):
        y=50+i*step
        body += '<text x="10" y="%.1f" fill="#ccc" font-size="10">%s</text>' % (y+10,escape(str(label)))
        body += '<rect x="210" y="%.1f" width="%.1f" height="%.1f" fill="#73bdff"/>' % (y,abs(v)/scale*650,max(2,step-3))
        body += '<text x="875" y="%.1f" fill="#ccc" font-size="10">%.1f</text>' % (y+10,v)
    return _svg(title,body)


def roam_delta_plot(roams):
    return _bars('Signal change per transition (dB)', [('R%d'%(i+1),r['rssi_delta']) for i,r in enumerate(roams) if r.get('rssi_delta') is not None])


def neighbor_plot(roams):
    return _bars('Best observed neighbor RSSI (dBm)', [('R%d'%(i+1),r['best_neighbor_rssi']) for i,r in enumerate(roams) if r.get('best_neighbor_rssi') is not None])


def dwell_plot(samples, ap_names=None):
    totals={}
    for a,b in zip(samples,samples[1:]):
        if a.get('bssid') and a.get('bssid')==b.get('bssid'):
            totals[a['bssid']]=totals.get(a['bssid'],0)+b['ts_epoch']-a['ts_epoch']
    return _bars('Observed AP dwell (seconds)', [((ap_names or {}).get(k,k),v) for k,v in totals.items()])
