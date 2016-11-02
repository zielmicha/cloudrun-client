from . import config
import requests, os, sys

TOKEN_PATH = config.CONFIG_PATH + '/token'
API_URL = os.environ.get('API_URL', 'https://cloudrun.io/api/')
VERSION = '0.1'

class ApiError(Exception):
    pass

class Api:
    def __init__(self):
        self.sess = None # type: requests.Session
        self.token = None # type: str

    def _create_session(self):
        if self.sess: return
        self.load_token()
        self.sess = requests.Session()
        self.sess.headers.update({
            'Authorization': 'Token ' + self.token,
            'User-Agent': 'cloudrun %s' % VERSION,
        })

    def login(self, login, password):
        resp = requests.post(API_URL + 'login', data={'username': login, 'password': password})
        resp.raise_for_status()
        self.token = resp.json()['token']
        self._store_token()

    def _store_token(self):
        with open(TOKEN_PATH, 'w') as f:
            os.chmod(TOKEN_PATH, 0o600)
            f.write(self.token + '\n')

    def load_token(self):
        if not os.path.exists(TOKEN_PATH):
            raise ApiError('Cannot read token file - please login with `cloudrun --login`')

        with open(TOKEN_PATH, 'r') as f:
            self.token = f.read().strip()

    def get_runner(self, runner_name):
        self._create_session()
        resp = self.sess.get(API_URL + 'runner/' + runner_name)
        if resp.status_code == 404:
            raise ApiError('Runner {0} doesn\'t exist yet - create it with `cloudrun --create-runner {0}`'.format(runner_name))
        resp.raise_for_status()
        return resp.json()

    def create_project(self, runner_name, project_name):
        self._create_session()
        resp = self.sess.post(API_URL + 'runner/' + runner_name + '/project/' + project_name)
        self.raise_for_response(resp)

    def add_ssh_key(self, runner_name, project_name, data):
        self._create_session()
        resp = self.sess.post(API_URL + 'runner/' + runner_name + '/project/' + project_name + '/keys',
                              data={'key': data})
        self.raise_for_response(resp)

    def create_runner(self, runner_name, size):
        self._create_session()
        resp = self.sess.post(API_URL + 'runner/' + runner_name,
                              data={'size': size})
        self.raise_for_response(resp)

    def stop_runner(self, runner_name):
        self._create_session()
        resp = self.sess.post(API_URL + 'runner/' + runner_name,
                              data={'state': 'off'})
        self.raise_for_response(resp)

    def raise_for_response(self, resp):
        resp.raise_for_status()
