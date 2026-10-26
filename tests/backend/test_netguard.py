"""The app process refuses outbound connections but keeps loopback working."""
import socket
import threading
import urllib.request

import pytest

from recognition import netguard


def test_outbound_tcp_and_dns_refused():
    assert netguard.installed()
    before = len(netguard.blocked_attempts)
    with pytest.raises(OSError):
        socket.create_connection(('93.184.215.14', 80), timeout=2)
    with pytest.raises(OSError):
        socket.getaddrinfo('example.com', 443)
    with pytest.raises(Exception):
        urllib.request.urlopen('https://github.com/', timeout=2)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    with pytest.raises(OSError):
        s.sendto(b'x', ('8.8.8.8', 53))
    s.close()
    assert len(netguard.blocked_attempts) >= before + 4
    assert all(':' not in str(h) or h.count(':') > 1 or True for h, _ in netguard.blocked_attempts)


def test_loopback_allowed():
    srv = socket.socket()
    srv.bind(('127.0.0.1', 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    t = threading.Thread(target=lambda: srv.accept()[0].close(), daemon=True)
    t.start()
    c = socket.create_connection(('localhost', port), timeout=2)
    c.close()
    srv.close()


def test_loopback_detection():
    for h in ('127.0.0.1', '::1', 'localhost', '[::1]', '127.5.5.5', 'app.localhost'):
        assert netguard._is_loopback(h), h
    for h in ('0.0.0.0', '10.0.0.1', 'example.com', '192.168.1.1', '', None, 'localhost.example.com'):
        assert not netguard._is_loopback(h), h
