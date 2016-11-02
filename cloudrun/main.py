from . import config, api, mount
from .runner import Runner, setup_key
from .socks_connect import socks_connect, parse_addr
import sys, argparse, os, getpass, subprocess, pipes

def get_project_and_path():
    fs_info = mount.find_fs(os.getcwd())

    if fs_info:
        return fs_info

    name = os.environ.get('CLOUDRUN_PROJECT')
    if name:
        return name, None

    name = config.get('default-project')
    if name:
        return name, None

    sys.exit('No project name specified. Either set CLOUDRUN_PROJECT variable or use `cloudrun --config-set default-project (name)`.\nThe name can be arbitrary and is used only to seperate different projects root filesystems.')

def get_runner():
    name, path = get_project_and_path()
    if '/' in name:
        runner_name, project_name = name.split('/', 1)
    else:
        runner_name, project_name = 'default', name

    runner = Runner(runner_name, project_name, path)
    runner.init()
    return runner

def cmd_config_set():
    ' Set configuration value '
    parser = argparse.ArgumentParser()
    parser.add_argument('key')
    parser.add_argument('value')
    ns = parser.parse_args()

    config.set(ns.key, ns.value)

def cmd_init():
    ' Create a new project '
    parser = argparse.ArgumentParser()
    ns = parser.parse_args()

    get_runner()

def cmd_create_runner():
    ' Create a new runner '
    parser = argparse.ArgumentParser()
    parser.add_argument('--size', default='auto')
    parser.add_argument('name')
    ns = parser.parse_args()

    api.Api().create_runner(ns.name, size=ns.size)

def cmd_mount():
    ' Mount a remote directory on your computer '
    parser = argparse.ArgumentParser()
    parser.add_argument('remotedir')
    parser.add_argument('localdir')
    ns = parser.parse_args()

    runner = get_runner()
    mount.fork_mount(runner, ns.remotedir, ns.localdir)

def cmd_run():
    ' Execute a command on a remote runner '
    parser = argparse.ArgumentParser()
    parser.add_argument('command', nargs=argparse.REMAINDER)
    ns = parser.parse_args()

    runner = get_runner()
    command_str = ' '.join(map(pipes.quote, ns.command or ['bash']))
    if runner.default_path is not None:
        command_str = 'cd %s; %s' % (pipes.quote(runner.default_path), command_str)

    os.execvp('ssh', ['ssh', '-t'] + runner.ssh_args + [runner.ssh_target, '--', command_str])

def upload_or_download(src, dst):
    runner = get_runner()
    ssh_cmd = ['ssh'] + runner.ssh_args
    cmd = ['rsync', '--info=progress2', '--no-inc-recursive', '-a', '--rsh', ' '.join(map(pipes.quote, ssh_cmd)), src, dst]
    sys.exit(subprocess.call(cmd))

def cmd_download():
    ' Download a file or directory from a remote runner'
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('destination', default='.', nargs='?')
    ns = parser.parse_args()

    upload_or_download('user@host:' + ns.source, ns.destination)

def cmd_upload():
    ' Upload a file or directory to a remote runner'
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('destination', default='', nargs='?')
    ns = parser.parse_args()

    upload_or_download(ns.source, 'user@host:' + ns.destination)

def cmd_stop():
    ' Stops the runner (preserving data stored on it) '
    get_runner().stop()

def cmd_login():
    ' Login to cloudrun.io '
    email = input('Email: ')
    password = getpass.getpass('Password: ')

    setup_key()
    api.Api().login(email, password)

def cmd_socks_connect():
    parser = argparse.ArgumentParser()
    parser.add_argument('socks')
    parser.add_argument('target')
    ns = parser.parse_args()

    socks_connect(parse_addr(ns.socks), parse_addr(ns.target))

commands = {
    'login': cmd_login,
    'config-set': cmd_config_set,
    'init': cmd_init,
    'mount': cmd_mount,
    'run': cmd_run,
    'download': cmd_download,
    'upload': cmd_upload,
    'stop': cmd_stop,
    'socks-connect': cmd_socks_connect,
    'create-runner': cmd_create_runner,
}

def main_wrapped():
    first_arg = '' if len(sys.argv) == 1 else sys.argv[1]
    if first_arg.startswith('--') and first_arg[2:] in commands:
        del sys.argv[1]
        commands[first_arg[2:]]()
    else:
        cmd_run()

def main():
    try:
        main_wrapped()
    except api.ApiError as err:
        sys.exit(str(err))

if __name__ == '__main__':
    main()
