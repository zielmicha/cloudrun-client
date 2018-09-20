import tty, termios, signal, fcntl, struct, os, threading, sys, time

def run_in_raw_mode(func):
    def inner(*args, **kwargs):
        fd = 0
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            func(*args, **kwargs)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    return inner

@run_in_raw_mode
def run_client(sock):
    fd = 0
    out_fd = 1

    def handle_resize():
        packed = fcntl.ioctl(fd, termios.TIOCGWINSZ, struct.pack('HHHH', 0, 0, 0, 0))
        h, w, _, _ = struct.unpack('HHHH', packed)
        msg = b'\1' + struct.pack('<II', h, w)
        sock.write(struct.pack('<I', len(msg)) + msg)
        sock.flush()

    def sigwinch(a, b):
        threading.Thread(target=handle_resize).start()

    # doing this from signal somehow causes "ssl.SSLError: Invalid error code"
    #signal.signal(signal.SIGWINCH, sigwinch)

    handle_resize()

    def reader():
        while True:
            data = os.read(fd, 4096)
            if not data: break
            sock.write(struct.pack('<I', len(data) + 1) + b'\0' + data)
            sock.flush()

    def writer():
        while True:
            size_b = sock.read(4)
            if not size_b: break
            size, = struct.unpack('<I', size_b)
            if size > 40000 or size == 0:
                raise Exception('invalid size')
            data = sock.read(size)
            if data[0] == 0:
                os.write(out_fd, data[1:])
            elif data[0] == 2:
                exit_code, = struct.unpack('<I', data[1:])
                sys.exit(exit_code)

    threading.Thread(target=reader, daemon=True).start()
    writer()
    sock.close()
    sys.exit(0)
