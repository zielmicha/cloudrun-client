import base64, hashlib, os, binascii

def key_fingerprint(line):
    key = base64.b64decode(line.strip().split()[1].encode('ascii'))
    return base64.b64encode(hashlib.sha256(key).hexdigest().encode())

def write_file(path, data):
    tmp = path + '.' + binascii.hexlify(os.urandom(5)).decode()
    with open(tmp, 'w') as f:
        f.write(data)
    os.rename(tmp, path)
