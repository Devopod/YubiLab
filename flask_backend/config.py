import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
WORKSPACES_DIR = os.path.join(os.path.dirname(BASE_DIR), 'user_workspaces')
DATABASE_PATH = os.path.join(BASE_DIR, 'yubilab.db')

SECRET_KEY = os.environ.get('SECRET_KEY', 'yubilab-secret-key-change-in-production')
NODE_ENGINE_URL = os.environ.get('NODE_ENGINE_URL', 'http://localhost:3001')

YUBIAI_API_URL = os.environ.get(
    'YUBIAI_API_URL',
    'https://yubiai.onrender.com/api/v1/chat'
)
YUBIAI_API_KEY = os.environ.get('YUBIAI_API_KEY', '')

os.makedirs(WORKSPACES_DIR, exist_ok=True)
