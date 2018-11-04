import argparse, tempfile, requests, subprocess, atexit, shutil, threading, socket, os, sys, json, urllib.parse, atexit, signal, getpass, socket
from . import common, simplepty

DEFAULT_SCAN_DIRS = ['/usr', '/bin', '/lib', '/lib64', '/etc', '/var']
CONFIG_PATH = os.path.expanduser('~/.config/cloudrun')

def manual_login(ns):
    if not os.path.exists(CONFIG_PATH):
        os.makedirs(CONFIG_PATH)
    shutil.copy(ns.cert, CONFIG_PATH + '/cert.pem')
    with open(CONFIG_PATH + '/api.json', 'w') as f:
        f.write(json.dumps({
            'host': ns.host,
            'key': ns.key,
            'manual': True,
        }))

def login(api_url):
    if not os.path.exists(CONFIG_PATH):
        os.makedirs(CONFIG_PATH)

    r = requests.post(api_url + '/api/fetch-token',
                      data={'hostname': socket.gethostname()})
    r.raise_for_status()
    url = r.json()['url']
    token = r.json()['token']

    print('Please visit ' + url + ' and accept linking this computer to your account.')

    with open(CONFIG_PATH + '/api.json', 'w') as f:
        f.write(json.dumps({
            'api_url': api_url,
            'api_token': token,
        }))

def stop_runner():
    settings = get_settings()

    r = requests.post(settings['api_url'] + '/api/runner-stop',
                      headers={'authorization': 'token ' + settings['api_token']})
    r.raise_for_status()

def get_settings():
    path = CONFIG_PATH + '/api.json'
    if not os.path.exists(path):
        sys.exit('Please log in with `cloudrun login`.')
    return json.load(open(path))

def request_runner_info(settings):
    r = requests.get(settings['api_url'] + '/api/runner-info?refresh=true',
                     headers={'authorization': 'token ' + settings['api_token']})
    r.raise_for_status()

    running = r.json()['running']
    if not running:
        print('Starting your cloud runner... It may take ~60 seconds.')
        r = requests.post(settings['api_url'] + '/api/runner-start',
                          headers={'authorization': 'token ' + settings['api_token']})
        r.raise_for_status()
        return request_runner_info(settings)
    else:
        return r.json()

def make_session():
    settings = get_settings()

    if not settings.get('manual'):
        if not settings.get('api_url'):
            sys.exit('You are not logged in. Please run `cloudrun login`.')

        info = request_runner_info(settings)
        with open(CONFIG_PATH + '/cert.pem', 'w') as f: # TODO:
            f.write(info['cert'])
        settings.update(info)

    s = requests.Session()
    s.headers['authorization'] = 'key ' + settings['key']
    s.mount('https://%s/' % settings['host'], common.HostNameIgnoringAdapter())

    settings['cert'] = CONFIG_PATH + '/cert.pem'

    return settings, s

def daemonize():
    with open('/dev/null', 'wb') as f:
        os.dup2(f.fileno(), 0)

    with open(CONFIG_PATH + '/log', 'ab') as f:
        os.dup2(f.fileno(), 1)
        os.dup2(f.fileno(), 2)

    if os.fork() != 0:
        os._exit(0)

    if os.fork() != 0:
        os._exit(0)

    os.setsid()

    with open(CONFIG_PATH + '/daemon.pid', 'w') as ff:
        ff.write(str(os.getpid()) + '\n')

    atexit.register(os.unlink, CONFIG_PATH + '/daemon.pid')

def daemon(foreground=False):
    settings, session = make_session()

    temp_dir = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, temp_dir)
    print('scanning...')
    server_path = os.path.dirname(__file__) + '/cloudrun-fs-server'
    subprocess.check_call([server_path, 'scan', temp_dir + '/meta'] + DEFAULT_SCAN_DIRS)
    print('uploading to', 'https://%s/update-meta' % (settings['host']))
    resp = session.post('https://%s/update-meta' % (settings['host']),
                        data=open(temp_dir + '/meta', 'rb'), verify=settings['cert'])
    resp.raise_for_status()

    print('starting...')
    server_process = subprocess.Popen([server_path, 'serve', 'unix:' + temp_dir + '/fs.sock'])

    if foreground:
        print('[daemon running]')
    else:
        print('[daemon started in background]')
        daemonize()

    sock1 = common.upgrade_request(host=settings['host'], cert=settings['cert'], path='/fs-stream',
                                   headers={'authorization': 'key ' + settings['key']})
    sock2 = socket.socket(socket.SOCK_STREAM, socket.AF_UNIX)
    sock2.connect(temp_dir + '/fs.sock')
    threading.Thread(target=lambda: common.pipe(sock2, sock1), daemon=True).start()
    common.pipe(sock1, sock2)
    print('pipe closed')

def get_daemon_pid():
    try:
        pid = int(open(CONFIG_PATH+ '/daemon.pid', 'r').read().strip())
    except Exception:
        return None

    try:
        os.kill(pid, 0)
        return pid
    except OSError:
        return pid

def restart():
    pid = get_daemon_pid()
    if pid:
        os.kill(pid, signal.SIGKILL)

    err = subprocess.call([sys.executable, '-m', 'cloudrun.client', 'daemon'])
    if err != 0:
        sys.exit(err)

def check_daemon():
    # FIXME: race condition
    if get_daemon_pid() != None: return

    print('[starting daemon]')

    err = subprocess.call([sys.executable, '-m', 'cloudrun.client', 'daemon'])
    if err != 0:
        sys.exit(err)

def execute(command):
    check_daemon()

    settings, session = make_session()
    isatty = os.isatty(0)

    info = {
        'command': command, 'environ': dict(os.environ),
        'uid': os.getuid(), 'gid': os.getgid(), 'groups': os.getgroups(),
        'tty': isatty,
    }

    sock1 = common.upgrade_request(host=settings['host'], cert=settings['cert'],
                                   path='/exec',
                                   headers={'authorization': 'key ' + settings['key']},
                                   body=info)
    if isatty:
        simplepty.run_client(sock1.makefile('rwb'))
    else:
        f = sock1.makefile('rwb')
        threading.Thread(target=lambda: common.pipe(f, sys.stdout)).start()
        common.pipe(sys.stdin, f)

def main():
    main_parser = argparse.ArgumentParser()
    subparsers = main_parser.add_subparsers(dest='subcommand')

    parser = subparsers.add_parser('manual-login', help='Login manually into the runner (without using cloud service)')
    parser.add_argument('--key', required=True)
    parser.add_argument('--host', required=True)
    parser.add_argument('--cert', required=True)

    parser = subparsers.add_parser('exec', help='Execute command')
    parser.add_argument('command', nargs='+')

    parser = subparsers.add_parser('stop-runner', help='Stop the runner')

    parser = subparsers.add_parser('daemon', help='Daemon')
    parser.add_argument('--foreground', action='store_true')

    parser = subparsers.add_parser('restart', help='Restart daemon to make sure system changes (e.g. installed packages) propagate to the cloud')

    parser = subparsers.add_parser('login', help='Login to cloudrun.io')
    parser.add_argument('--api-url', default='https://cloudrun.io')

    ns = main_parser.parse_args()
    if ns.subcommand == 'manual-login':
        manual_login(ns)
    elif ns.subcommand == 'login':
        login(ns.api_url)
    elif ns.subcommand == 'exec':
        execute(ns.command)
    elif ns.subcommand == 'daemon':
        daemon(foreground=ns.foreground)
    elif ns.subcommand == 'restart':
        restart()
    elif ns.subcommand == 'stop-runner':
        stop_runner()
    else:
        main_parser.print_usage()
        sys.exit('invalid subcommand')

if __name__ == '__main__':
    main()
