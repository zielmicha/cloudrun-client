import argparse, tempfile, requests, subprocess, atexit, shutil, threading, socket, os, sys, json, urllib.parse
from . import common, simplepty

DEFAULT_SCAN_DIRS = ['/usr', '/bin', '/lib', '/lib64', '/etc', '/var']
CONFIG_PATH = os.path.expanduser('~/.config/cloudrun')

def manual_login(ns):
    if not os.path.exists(CONFIG_PATH):
        os.makedirs(CONFIG_PATH)
    shutil.copy(ns.cert, CONFIG_PATH + '/cert.pem')
    with open(CONFIG_PATH + '/machine.json', 'w') as f:
        f.write(json.dumps({
            'host': ns.host,
            'key': ns.key,
        }))

def get_settings():
    return json.load(open(CONFIG_PATH + '/machine.json'))

def make_session():
    settings = get_settings()

    s = requests.Session()
    s.headers['authorization'] = 'key ' + settings['key']
    s.mount('https://%s/' % settings['host'], common.HostNameIgnoringAdapter())

    settings['cert'] = CONFIG_PATH + '/cert.pem'

    return settings, s

def daemon():
    settings, session = make_session()

    temp_dir = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, temp_dir)
    print('scanning...')
    subprocess.check_call(['./cloudrun-fs-server', 'scan', temp_dir + '/meta', *DEFAULT_SCAN_DIRS])
    resp = session.post('https://%s/update-meta' % (settings['host']),
                        data=open(temp_dir + '/meta', 'rb'), verify=settings['cert'])
    resp.raise_for_status()

    print('starting...')
    server_process = subprocess.Popen(['./cloudrun-fs-server', 'serve', 'unix:' + temp_dir + '/fs.sock'])

    sock1 = common.upgrade_request(host=settings['host'], cert=settings['cert'], path='/fs-stream',
                                   headers={'authorization': 'key ' + settings['key']})
    sock2 = socket.socket(socket.SOCK_STREAM, socket.AF_UNIX)
    sock2.connect(temp_dir + '/fs.sock')
    threading.Thread(target=lambda: common.pipe(sock2, sock1), daemon=True).start()
    common.pipe(sock1, sock2)
    print('pipe closed')

def execute(command):
    settings, session = make_session()

    info = {
        'command': command, 'environ': dict(os.environ),
        'uid': os.getuid(), 'gid': os.getgid(), 'groups': os.getgroups()
    }

    sock1 = common.upgrade_request(host=settings['host'], cert=settings['cert'],
                                   path='/exec',
                                   headers={'authorization': 'key ' + settings['key']},
                                   body=info)
    simplepty.run_client(sock1.makefile('rwb'))

if __name__ == '__main__':
    main_parser = argparse.ArgumentParser()
    subparsers = main_parser.add_subparsers(dest='subcommand')

    parser = subparsers.add_parser('manual-login', help='Login manually into the runner (without using cloud service)')
    parser.add_argument('--key', required=True)
    parser.add_argument('--host', required=True)
    parser.add_argument('--cert', required=True)

    parser = subparsers.add_parser('exec', help='Execute command')
    parser.add_argument('command', nargs='+')
    parser = subparsers.add_parser('daemon', help='Daemon')

    ns = main_parser.parse_args()
    if ns.subcommand == 'manual-login':
        manual_login(ns)
    elif ns.subcommand == 'exec':
        execute(ns.command)
    elif ns.subcommand == 'daemon':
        daemon()
    else:
        parser.print_usage()
        sys.exit('invalid subcommand')
