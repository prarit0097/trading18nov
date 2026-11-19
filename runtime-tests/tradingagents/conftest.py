"""Offline boundary for the installed-wheel runtime checks; never load .env."""
import os
import socket
from pathlib import Path

import pytest
import dotenv

os.environ['PYTHON_DOTENV_DISABLED'] = '1'
for key in list(os.environ):
    if key.startswith(('TRADINGAGENTS_', 'LANGCHAIN_', 'LANGSMITH_')) or key.endswith(('_API_KEY', '_API_TOKEN')):
        os.environ.pop(key, None)
for key in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GOOGLE_API_KEY'):
    os.environ[key] = 'runtime-test-placeholder-not-a-real-key'
os.environ['LANGSMITH_TRACING'] = 'false'
dotenv.find_dotenv = lambda *a, **k: ''
dotenv.load_dotenv = lambda *a, **k: False
root = Path(__file__).resolve().parent / 'runtime-data'
for key, suffix in [('TRADINGAGENTS_RESULTS_DIR', 'results'), ('TRADINGAGENTS_CACHE_DIR', 'cache'), ('TRADINGAGENTS_MEMORY_LOG_PATH', 'memory.md')]:
    os.environ[key] = str(root / suffix)

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError('External network denied by local runtime harness')
    monkeypatch.setattr(socket.socket, 'connect', refuse)
    monkeypatch.setattr(socket.socket, 'connect_ex', refuse)
    monkeypatch.setattr(socket, 'getaddrinfo', refuse)
    from curl_cffi import requests
    monkeypatch.setattr(requests.Session, 'request', refuse)
    monkeypatch.setattr(requests.AsyncSession, 'request', refuse)
