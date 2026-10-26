"""Refuse outbound network connections from the app process (loopback is allowed).

Installed by app.py before any model code is imported, so a library that tries to download weights,
tokenizers or telemetry at runtime fails loudly instead of silently reaching the internet.
"""
import ipaddress
import socket
import threading

_lock = threading.Lock()
_installed = False
blocked_attempts = []  # (host, port) only; never request contents


class NetworkBlocked(OSError):
    pass


def _is_loopback(host) -> bool:
    if host is None:
        return False
    if isinstance(host, bytes):
        host = host.decode('ascii', 'ignore')
    host = str(host).strip('[]').lower()
    if host in ('localhost', 'localhost.', ''):
        return host != ''
    if host.endswith('.localhost'):
        return True
    try:
        return ipaddress.ip_address(host.split('%')[0]).is_loopback
    except ValueError:
        return False


def _check(address):
    if isinstance(address, tuple) and address:
        host, port = address[0], (address[1] if len(address) > 1 else None)
    else:  # AF_UNIX path or similar: local only
        return
    if not _is_loopback(host):
        blocked_attempts.append((str(host), port))
        raise NetworkBlocked(f'Outbound network access is disabled in Say the Math (attempted {host}).')


def install():
    global _installed
    with _lock:
        if _installed:
            return
        orig_connect = socket.socket.connect
        orig_connect_ex = socket.socket.connect_ex
        orig_getaddrinfo = socket.getaddrinfo
        orig_sendto = socket.socket.sendto

        def connect(self, address):
            if self.family in (socket.AF_INET, socket.AF_INET6):
                _check(address)
            return orig_connect(self, address)

        def connect_ex(self, address):
            if self.family in (socket.AF_INET, socket.AF_INET6):
                _check(address)
            return orig_connect_ex(self, address)

        def sendto(self, data, *args):
            address = args[-1]
            if self.family in (socket.AF_INET, socket.AF_INET6):
                _check(address)
            return orig_sendto(self, data, *args)

        def getaddrinfo(host, *args, **kwargs):
            if host is not None and not _is_loopback(host):
                blocked_attempts.append((str(host), args[0] if args else None))
                raise NetworkBlocked(f'Outbound network access is disabled in Say the Math (lookup of {host}).')
            return orig_getaddrinfo(host, *args, **kwargs)

        socket.socket.connect = connect
        socket.socket.connect_ex = connect_ex
        socket.socket.sendto = sendto
        socket.getaddrinfo = getaddrinfo
        _installed = True


def installed() -> bool:
    return _installed
