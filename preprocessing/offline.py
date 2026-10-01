"""Reject network connection attempts during preprocessing."""

from contextlib import contextmanager
import socket


@contextmanager
def network_disabled():
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_connection = socket.create_connection

    def deny(*args, **kwargs):
        raise RuntimeError("Network access is disabled for snapshot preprocessing")

    socket.socket.connect = deny
    socket.socket.connect_ex = deny
    socket.create_connection = deny
    try:
        yield
    finally:
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex
        socket.create_connection = original_connection
