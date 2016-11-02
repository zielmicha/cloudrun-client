from . import config
import os, json, fcntl, pipes, subprocess, traceback

STATUS_PATH = config.CONFIG_PATH + '/mounts'
FAKE_MOUNTS = False

def read_info():
    if not os.path.exists(STATUS_PATH):
        return []

    with open(STATUS_PATH) as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        return json.loads(f.read())

def get_mount_point(path: str) -> str:
    path = os.path.realpath(path)
    while not os.path.ismount(path):
        path = os.path.dirname(path)
    return path

def find_fs(path):
    path = os.path.realpath(path)
    mntpath = get_mount_point(path)
    relpath = os.path.relpath(path, mntpath)

    for info in read_info():
        if info['mountpoint'] == mntpath:
            return info['project'], os.path.join(info['remote-path'], relpath)

    return None

def unmount_runner(name: str) -> None:
    for info in read_info():
        if info['runner'] == name:
            unmount(info['mountpoint'])

def unmount(mountpoint: str) -> None:
    with open(STATUS_PATH, 'a+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)

        f.seek(0)
        all_info = json.loads(f.read() or '[]')
        my_info = [ info for info in all_info if info['mountpoint'] == mountpoint ]
        other_info = [ info for info in all_info if info['mountpoint'] != mountpoint ]

        if FAKE_MOUNTS:
            print('umount', mountpoint)
        else:
            subprocess.call(['fusermount', '-u', '-z', mountpoint])

        for info in my_info:
            try:
                if FAKE_MOUNTS:
                    print('kill', info['pid'])
                os.kill(info['pid'], 15)
            except OSError:
                pass

        f.seek(0)
        os.ftruncate(f.fileno(), 0)
        f.write(json.dumps(other_info))

def mount(runner, remote_path: str, mountpoint: str) -> None:
    mountpoint = os.path.realpath(mountpoint)
    unmount(mountpoint)
    sshfs_cmd = (['sshfs', '-f', '-C', '-o', 'reconnect,delay_connect'] +
                 runner.base_ssh_args + ['user@host:' + remote_path, mountpoint])

    if FAKE_MOUNTS:
        process = subprocess.Popen(['sleep', '100h'])
        print('mount', ' '.join(map(pipes.quote, sshfs_cmd)))
    else:
        process = subprocess.Popen(sshfs_cmd)

    with open(STATUS_PATH, 'a+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)

        f.seek(0)
        all_info = json.loads(f.read() or '[]')
        all_info.append({'runner': runner.runner_name, 'project': runner.project_name,
                         'mountpoint': mountpoint, 'remote-path': remote_path,
                         'pid': process.pid})

        f.seek(0)
        os.ftruncate(f.fileno(), 0)
        f.write(json.dumps(all_info))

    process.wait()
    unmount(mountpoint)

def fork_mount(runner, remote_path: str, mountpoint: str) -> None:
    if os.fork() == 0:
        try:
            try:
                mount(runner, remote_path, mountpoint)
            except:
                traceback.print_exc()
        finally:
            os._exit(0)
