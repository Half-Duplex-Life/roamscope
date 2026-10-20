"""Live dashboard: serve the output dir over HTTP while capturing.

--live regenerates report.html every few seconds and serves it at
http://127.0.0.1:PORT/report.html with auto-refresh.
"""
import functools
import http.server
import socketserver
import threading


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def start_server(directory, port):
    handler = functools.partial(_QuietHandler, directory=directory)
    # allow_reuse so quick restarts don't trip over TIME_WAIT
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd
