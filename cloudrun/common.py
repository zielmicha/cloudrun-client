import requests, ssl, requests.adapters, socket, json
from requests.packages.urllib3.poolmanager import PoolManager

class HostNameIgnoringAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False):
        self.poolmanager = PoolManager(num_pools=connections,
                                       maxsize=maxsize,
                                       block=block,
                                       assert_hostname=False)

def upgrade_request(host, cert, path, headers, body=None):
    context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_verify_locations(cert)
    context.check_hostname = False

    conn = context.wrap_socket(socket.create_connection((host, 443)))
    body_s = b''
    if body is not None:
        body_s = json.dumps(body).encode()
        headers = dict({'content-length': len(body_s), 'content-type': 'application/json'}, **headers)

    conn.sendall(('POST %s HTTP/1.0\r\n%s\r\n' % (path, ''.join( '%s: %s\r\n' % (k, v) for k, v in headers.items() ))).encode('utf8'))
    conn.sendall(body_s)

    resp = conn.recv(1)
    if resp == b'+':
        return conn
    else:
        raise Exception('connection failed (status: %r)' % resp)

def pipe(sock1, sock2):
    try:
        while True:
            data = sock1.recv(40960)
            if not data: break
            sock2.sendall(data)
    except IOError as err:
        print(err)
