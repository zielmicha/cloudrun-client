import json, os

CONFIG_PATH = os.path.expanduser('~/.config/cloudrun')
path = CONFIG_PATH + '/config.json'

def _load():
    if not os.path.exists(path):
        return {}

    with open(path) as f:
        return json.load(f)

def _store(config):
    if not os.path.exists(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))

    with open(path + '.tmp', 'w') as f:
        f.write(json.dumps(config, indent=4) + '\n')

    os.rename(path + '.tmp', path)

def get(key, default=None):
    d = _load()
    try:
        return str(d[key])
    except KeyError:
        return default

def get_bool(key, default=None):
    v = get(key, None)
    if v == None:
        return default
    if v.lower() == 'true':
        return True
    elif v.lower() == 'false':
        return False
    else:
        raise ValueError('invalid boolean configuration value for key %r: %r' % (key, v))

def set(key, value):
    config = _load()
    config[key] = value
    _store(config)
