from . import config
import os, json, fcntl, pipes

STATUS_PATH = config.CONFIG_PATH + '/mounts'

def read_info():
    if not os.path.exists(STATUS_PATH):
        return []

    with open(STATUS_PATH) as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        return json.loads(f.read())

def get_mount_point(path):
    path = os.path.realpath(path)
    while not os.path.ismount(path):
        path = os.path.dirname(path)
    return path

def find_fs(path):
    path = get_mount_point(path)

    for info in read_info():
        if info['mountpoint'] == path:
            return info['project'], info['remote-path']

    return None

def unmount_runner(name):
    for info in read_info():
        if info['runner'] == name:
            unmount(info['mountpoint'])

def unmount(mountpoint):
    with open(STATUS_PATH, 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)

        all_info = json.loads(f.read())
        my_info = [ info for info in all_info if info['mountpoint'] == mountpoint ]
        other_info = [ info for info in all_info if info['mountpoint'] != mountpoint ]

        subprocess.call(['fusermount', '-u', '-z', mountpoint])

        for info in my_info:
            try:
                os.kill(info['pid'], 15)
            except OSError:
                pass

        f.seek(0)
        os.ftruncate(f, 0)
        f.write(json.dumps(other_info))

def mount(runner, remote_path, mountpoint):
    mountpoint = os.path.realpath(mountpoint)
    unmount(mountpoint)
    command = ' '.join(map(pipes.quote, ['ssh'] + runner.ssh_args))
    process = subprocess.Popen(['sshfs', '-f', '-C', '-o', 'reconnect,delay_connect',
                                '-ossh_command=' + command, 'user@host:' + remote_path, mountpoint])

    with open(STATUS_PATH, 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)

        all_info = json.loads(f.read())
        all_info.append({'runner': runner.runner_name, 'project': project.project_name,
                         'mountpoint': mountpoint, 'remote-path': remote_path,
                         'pid': process.pid})

        f.seek(0)
        os.ftruncate(f, 0)
        f.write(json.dumps(other_info))


    unmount(mountpoint)
