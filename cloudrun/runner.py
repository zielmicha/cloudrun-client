from typing import Dict, List, Any
from . import config, api, misc
import os, subprocess, binascii, time, sys

cache_path = os.path.expanduser('~/.cache/cloudrun')
SSH_KEY_PATH = config.CONFIG_PATH + '/id'

def log(s):
    if sys.stderr.isatty():
        print('\033[1;37m[cloudrun]\033[0m', s, file=sys.stderr)

def setup_key():
    if not os.path.exists(SSH_KEY_PATH):
        subprocess.check_call(['ssh-keygen',
                               '-N', '',
                               '-f', SSH_KEY_PATH], stdout=open('/dev/null', 'w'))

class Runner:
    def __init__(self, runner_name: str, project_name: str, default_path: str) -> None:
        self.api = api.Api()
        self.runner_name = runner_name
        self.project_name = project_name
        self.default_path = default_path

        # argumetns that should be passes to SSH
        self.ssh_args = None # type: List[str]
        # SSH target (fake, ProxyCommand anyway ignores it)
        self.ssh_target = 'user@host'

        self.project_info = None # type: Dict[str, Any]

    def init(self):
        '''
        Fetches remote address of a runner/project. Launches them if needed.
        '''
        self._init_remote()
        self._init_params()

    def _init_params(self) -> None:
        control_dir = cache_path + '/ssh/control_'
        if not os.path.exists(control_dir):
            os.makedirs(control_dir)

        id = binascii.hexlify(self.runner_name.encode()).decode() + '_' + binascii.hexlify(self.project_name.encode()).decode()
        control_path = control_dir + id

        known_hosts_data = '* ' + self.project_info['ssh-host-key']
        external_ip = self.project_info['external-ip']
        internal_ip = self.project_info['internal-ip']

        known_hosts_file = cache_path + '/ssh/known_hosts_' + id
        misc.write_file(known_hosts_file, known_hosts_data)

        self.base_ssh_args = [
            '-oIdentityFile=' + SSH_KEY_PATH,
            '-oUserKnownHostsFile=' + known_hosts_file,
            '-oStrictHostKeyChecking=yes',
            '-oProxyCommand={} --socks-connect {}:443 {}:22'.format(os.path.realpath(sys.argv[0]), external_ip, internal_ip),
        ] # for SSHFS

        self.ssh_args = self.base_ssh_args + [ # for interactive usage
            '-oControlPersist=600',
            '-oControlMaster=auto',
            '-oControlPath=%s' % control_path,
            '-oServerAliveInterval=30', # keeps NAT alive
        ]
        if config.get_bool('agent-forwarding'):
            self.ssh_args.append('-T')

        self.ssh_target = 'user@host'

    def _init_remote(self) -> None:
        delay = 1
        while True:
            info = self.get_remote_info()
            if info['state'] in ('deploying', 'starting'):
                log('Runner is starting, please wait')
                time.sleep(delay)
                delay = min(delay * 2, 5)
            elif info['state'] == 'off':
                log('Launching runner...')
                self.api.create_runner(self.runner_name, 'none')
            elif info['state'] == 'on':
                break
            else:
                raise ValueError('invalid state')

        if self.project_name not in info['projects']:
            # TODO: race condition
            log('Creating project ' + self.project_name + '...')
            self.api.create_project(self.runner_name, self.project_name)
            info = self.get_remote_info()

        self.project_info = info['projects'][self.project_name]

        ssh_key_data = open(SSH_KEY_PATH + '.pub', 'r').read()
        ssh_key_fingerprint = misc.key_fingerprint(ssh_key_data)

        if ssh_key_fingerprint not in self.project_info['ssh-authorized']:
            self.api.add_ssh_key(self.runner_name, self.project_name, ssh_key_data)

    def get_remote_info(self) -> Dict[str, Any]:
        return self.api.get_runner(self.runner_name)

    def stop(self) -> None:
        self.api.stop_runner(self.runner_name)
