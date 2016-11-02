from typing import Tuple
import subprocess, socket, sys, os

def socks_connect(socks_addr: Tuple[str, int], target_addr: Tuple[str, int]):
    import fcntl, threading, struct, socket, select

    def recvall(sock, k):
        data = b''
        while len(data) < k:
            v = sock.recv(k - len(data))
            if not v: break
            data += v
        return data

    sock = socket.socket()
    sock.connect(socks_addr)
    f = sock.makefile('rwb')
    data = b'\x05\x01\x00\x05\x01\x00\x01' +  socket.inet_aton(target_addr[0]) + struct.pack('!H', target_addr[1])
    sock.sendall(data)
    resp = recvall(sock, 2 + 10)
    if not resp.startswith(b'\x05\x00\x05\x00') or len(resp) != 12:
        sys.exit('SOCKS server returned bad response (not authenticated to the wireless network?)')

    p = subprocess.Popen(['cat'], stdout=sock, stdin=sys.stdin)
    subprocess.Popen(['cat'], stdout=sys.stdout, stdin=sock).wait()
    p.kill()
    os._exit(0)

def parse_addr(s: str) -> Tuple[str, int]:
    host, port = s.rsplit(':', 1)
    return (host, int(port))
