#!/usr/bin/env python3
import os, argparse, sys, yaml, binascii, subprocess, pipes, getpass, requests, base64, hashlib, time

class NoProjectFound(Exception): pass

CACHE_DIR = os.path.expanduser('~/.cache/cloudrun')
CONFIG_DIR = os.path.expanduser('~/.config/cloudrun')
API_URL = os.environ.get('API_URL', 'https://cloudrun.io/api/')
VERSION = '0.1'

def find_project():
    current = os.path.abspath('.')
    while current != '/':
        if os.path.exists(os.path.join(current, '.cloudrun.yml')):
            return current

        if os.path.ismount(current):
            break

        current = os.path.dirname(current)

    raise NoProjectFound()

def log(s):
    if sys.stderr.isatty():
        print('\033[1;37m[cloudrun]\033[0m', s, file=sys.stderr)

def ssh_quote(args):
    return list(map(pipes.quote, args))

class Message(Exception):
    pass

class Runner:
    def __init__(self):
        control_dir = CACHE_DIR + '/ssh/control_'
        if not os.path.exists(control_dir):
            os.makedirs(control_dir)
        control_path = control_dir + binascii.hexlify(self.id.encode()).decode()

        self.ssh_base_cmd = ['ssh'] + self._ssh_base
        self.ssh_base_cmd += [
            '-oControlPersist=600',
            '-oControlMaster=auto',
            '-oControlPath=%s' % control_path]
        self.ssh_cmd = self.ssh_base_cmd  + [self.ssh_target]

class SshRunner(Runner):
    def __init__(self, conn_info):
        self.conn_info = conn_info
        self._ssh_base = []
        self.ssh_target = conn_info
        self._id = 'ssh:%s' % conn_info
        Runner.__init__(self)

def key_fingerprint(line):
    key = base64.b64decode(line.strip().split()[1].encode('ascii'))
    return base64.b64encode(hashlib.sha256(key).hexdigest().encode())

def write_file(path, data):
    tmp = path + '.' + binascii.hexlify(os.urandom(5)).decode()
    with open(tmp, 'w') as f:
        f.write(data)
    os.rename(tmp, path)

def raise_for_response(resp):
    resp.raise_for_status()

class CloudRunRunner(Runner):
    ssh_key_path = CONFIG_DIR + '/id'
    token_path = CONFIG_DIR + '/token'

    def __init__(self, project_name, args):
        self._init_args(project_name, args)
        self.sess = self._create_session()
        self._init_remote()
        self._init_params()
        Runner.__init__(self)

    def _init_args(self, project_name, args):
        if any( '=' not in t for t in args[1:] ):
            raise ValueError('invalid target specification (%s)' % args)
        attrs = dict( t.split('=', 1) for t in args[1:] )
        self.project_name = attrs.get('project', project_name)
        self.id = attrs.get('id', 'default')

    @classmethod
    def _create_session(cls):
        sess = requests.Session()
        sess.headers.update({
            'Authorization': 'Token ' + cls.get_token(),
            'User-Agent': 'cloudrunctl %s' % VERSION,
        })
        return sess

    def _init_remote(self):
        delay = 1
        while True:
            info = self.get_remote_info()
            if info['state'] in ('deploying', 'starting'):
                log('Runner is starting, please wait')
                time.sleep(delay)
                delay = min(delay * 2, 5)
            elif info['state'] == 'off':
                log('Launching runner...')
                self.create_runner(self.id, 'none')
            elif info['state'] == 'on':
                break
            else:
                raise ValueError('invalid state')

        if self.project_name not in info['projects']:
            # TODO: race condition
            log('Creating project ' + self.project_name + '...')
            self.create_project()
            info = self.get_remote_info()

        self.project_info = info['projects'][self.project_name]

        ssh_key_data = open(self.ssh_key_path + '.pub', 'r').read()
        ssh_key_fingerprint = key_fingerprint(ssh_key_data)

        if ssh_key_fingerprint not in self.project_info['ssh-authorized']:
            self.add_ssh_key(ssh_key_data)

    def get_remote_info(self):
        resp = self.sess.get(API_URL + 'runner/' + self.id)
        if resp.status_code == 404:
            raise Message('Runner {} doesn\'t exist yet - create it with `cloudrunctl create-runner {}`'.format(self.id, self.id))
        resp.raise_for_status()
        return resp.json()

    def create_project(self):
        resp = self.sess.post(API_URL + 'runner/' + self.id + '/project/' + self.project_name)
        raise_for_response(resp)

    def add_ssh_key(self, data):
        resp = self.sess.post(API_URL + 'runner/' + self.id + '/project/' + self.project_name + '/keys',
                              data={'key': data})
        raise_for_response(resp)

    @classmethod
    def create_runner(cls, name, size):
        sess = cls._create_session()
        resp = sess.post(API_URL + 'runner/' + name,
                         data={'size': size})
        raise_for_response(resp)

    @classmethod
    def stop_runner(cls, name):
        sess = cls._create_session()
        resp = sess.post(API_URL + 'runner/' + name,
                         data={'state': 'off'})
        raise_for_response(resp)

    def _init_params(self):
        known_hosts_data = '* ' + self.project_info['ssh-host-key']
        external_ip = self.project_info['external-ip']
        internal_ip = self.project_info['internal-ip']

        known_hosts_file = CACHE_DIR + '/ssh/known_hosts_' + binascii.hexlify(self.id.encode()).decode() + '_' + binascii.hexlify(self.project_name.encode()).decode()
        write_file(known_hosts_file, known_hosts_data)
        self._ssh_base = [
            '-oIdentityFile=' + self.ssh_key_path,
            '-oUserKnownHostsFile=' + known_hosts_file,
            '-oStrictHostKeyChecking=yes',
            '-oProxyCommand={} socks-connect {}:443 {}:22'.format(os.path.realpath(sys.argv[0]), external_ip, internal_ip),
        ]
        self.ssh_target = 'user@host'

    @classmethod
    def setup_key(cls):
        if not os.path.exists(cls.ssh_key_path):
            subprocess.check_call(['ssh-keygen',
                                   '-N', '',
                                   '-f', cls.ssh_key_path], stdout=open('/dev/null', 'w'))

    @classmethod
    def get_token(cls):
        try:
            with open(cls.token_path) as f:
                return f.read().strip()
        except IOError:
            raise Message('Cannot read token file. Please login with `cloudrunctl login`.')

    @classmethod
    def login(cls, login, password):
        resp = requests.post(API_URL + 'login', data={'username': login, 'password': password})
        resp.raise_for_status()
        token = resp.json()['token']

        with open(cls.token_path, 'w') as f:
            os.chmod(cls.token_path, 0o600)
            f.write(token + '\n')

class CloudRun:
    def __init__(self, ns):
        self.runner_spec = ns.runner
        self.target_dir = ns.target_dir

    def init(self):
        self.project_dir = find_project()
        with open(self.project_dir + '/.cloudrun.yml', 'r') as f:
            self.config = yaml.load(f)

        if not self.target_dir:
            self.target_dir = self.config.get('target-dir')

        if not self.target_dir:
            self.target_dir = self.project_dir

        self.project_name = self.config['name']
        self.output = self.config.get('output', [])
        self.ignore = self.config.get('ignore', [])
        self.runner = self._create_runner()

        if self.ssh_run(['test', '-w', self.target_dir], check=False):
            self.ssh_run(['sudo', 'mkdir', '-p', self.target_dir])
            user_id = self.ssh_output(['id', '-u']).decode().strip()
            self.ssh_run(['sudo', 'chown', user_id, self.target_dir])

    def ssh_output(self, cmd):
        return subprocess.check_output(self.runner.ssh_cmd + ['--'] + ssh_quote(cmd))

    def ssh_run(self, command, check=True, tty=False):
        cmd = list(self.runner.ssh_cmd)
        if tty:
            cmd.append('-t')
        cmd += ['--'] + ssh_quote(command)
        code = subprocess.call(cmd)
        if code != 0 and check:
            raise subprocess.CalledProcessError(code, ' '.join(cmd))
        return code

    def _create_runner(self):
        if not self.runner_spec:
            self.runner_spec = self.config.get('runner')

        if not self.runner_spec:
            self.runner_spec = 'default'

        if ':' not in self.runner_spec:
            self.runner_spec = 'cloudrun:id=' + self.runner_spec

        args = self.runner_spec.split(':')
        if len(args) < 2:
            raise ValueError('Bad runner specification')

        if args[0] == 'ssh':
            return SshRunner(':'.join(args[1:]))
        elif args[0] == 'cloudrun':
            return CloudRunRunner(project_name=self.project_name,
                                  args=args)
        else:
            raise ValueError('Bad runner specification')

    def run_command(self, command):
        sh_command = ' '.join(map(pipes.quote, command))
        log('Running ' + sh_command)
        script = 'cd %s && %s' % (pipes.quote(self.target_dir), sh_command)
        return self.ssh_run(['sh', '-c', script], check=False, tty=True)

    def sync(self, dir, exclude=[], include=None):
        filters = []
        for pattern in exclude:
            filters.append('--exclude=' + pattern)

        if include:
            for pattern in include:
                filters.append('--include=' + pattern)
            # from http://blog.mudflatsoftware.com/blog/2012/10/31/tricks-with-rsync-filter-rules/
            filters.append('--filter=-! */')

        ssh_cmd = ' '.join(map(pipes.quote, self.runner.ssh_base_cmd))
        cmd = ['rsync', '-z', '--info=progress2', '--no-inc-recursive', '--delete', '-a', '-e', ssh_cmd] + filters
        local = self.project_dir + '/'
        remote = self.runner.ssh_target + ':' + self.target_dir + '/'

        if dir == 'download':
            local, remote = remote, local

        cmd += [local, remote]

        # print(' '.join(map(pipes.quote, cmd)))
        subprocess.check_call(cmd)
    
    def upload(self):
        log('Uploading changes...')
        self.sync(dir='upload', exclude=self.output + self.ignore)

    def download(self, all=False):
        log('Downloading results...')

        if all:
            self.sync(dir='download', exclude=self.ignore)
        else:
            self.sync(dir='download', include=self.output)

def socks_connect(socks_addr, target_addr):
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

def parse_addr(s):
    host, port = s.rsplit(':', 1)
    return (host, int(port))

def validate_name(name):
    pass

def init_project(name):
    validate_name(name)
    filename = '.cloudrun.yml'
    if os.path.exists(filename):
        sys.exit('cloudrun project already exists in the current directory.')

    with open(filename, 'w') as f:
        f.write('''# Project name is used to isolate different projects. Each project gets a dedicated OS instance.
name: %s

# sync settings
# Ignore these files when syncing between cloud and localhost.
ignore:
- 'build_dir/*'
- '*.o'
- '*.lo'
- '.cloudrun.yml'

# Fetch these files from the cloud after running command.
output:
- bin/*
''' % name)

def main(ns):
    if ns.subcommand == 'run':
        runner = CloudRun(ns)
        runner.init()

        if not ns.no_upload:
            runner.upload()

        status = runner.run_command(ns.command or ['bash'])
        if status != 0:
            log('command exited with status %d' % status)

        if not ns.no_download:
            runner.download(all=ns.dl)

        sys.exit(status)
    elif ns.subcommand == 'create-runner':
        log('Creating runner %s (size: %s). It may take a few minutes.' % (ns.name, ns.size))
        CloudRunRunner.create_runner(ns.name, size=ns.size)
    elif ns.subcommand == 'stop':
        CloudRunRunner.stop_runner(ns.name)
    elif ns.subcommand == 'socks-connect':
        socks_connect(parse_addr(ns.socks), parse_addr(ns.target))
    elif ns.subcommand == 'login':
        login = input('Login: ')
        password = getpass.getpass('Password: ')
        CloudRunRunner.login(login, password)
        CloudRunRunner.setup_key()
    elif ns.subcommand == 'init':
        init_project(ns.name)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    if os.path.basename(sys.argv[0]) == 'cloudrun':
        # `cloudrun` is an alias for `cloudrunctl run`
        sys.argv[1:1] = ['run']

    try: os.makedirs(CACHE_DIR + '/ssh')
    except OSError: pass

    try: os.makedirs(CONFIG_DIR)
    except OSError: pass

    parser = argparse.ArgumentParser()

    def add_base_args(parser):
        parser.add_argument('--runner', '-r',
                            help='Select a runner to run commands on')
        parser.add_argument('--target-dir', metavar='DIR',
                            help='Use DIR as a directory for this project (by default, use the same path)')

    subparsers = parser.add_subparsers(dest='subcommand')

    subparser = subparsers.add_parser('run', help='Execute a command on a cloud runner')
    subparser.add_argument('--no-upload', help="Don't wait until changes are uploaded before starting.", action='store_true')
    subparser.add_argument('--no-download', help="Don't download changes after finishing.", action='store_true')
    subparser.add_argument('--dl', '--download-all', help="Download all non-ignored files from the runner after finishing the command. Useful for running `git clone` etc.", action='store_true')
    add_base_args(subparser)
    subparser.add_argument('command', nargs=argparse.REMAINDER)

    subparser = subparsers.add_parser('create-runner')
    subparser.add_argument('--size', help='Runner size', default='auto')
    subparser.add_argument('name', help='Runner name')

    subparser = subparsers.add_parser('stop', help='Stop a runner')
    subparser.add_argument('name', help='Runner name', default='default', nargs='?')

    subparser = subparsers.add_parser('socks-connect', help='Establish a connection via SOCKS server - internal')
    subparser.add_argument('socks')
    subparser.add_argument('target')

    subparser = subparsers.add_parser('init', help='Initialize project in current directory')
    subparser.add_argument('name', help='Project name')

    subparser = subparsers.add_parser('login')

    ns = parser.parse_args()

    try:
        main(ns)
    except Message as m:
        log(str(m))
        sys.exit(1)
