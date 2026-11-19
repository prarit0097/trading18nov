import socket,pytest
@pytest.fixture(autouse=True)
def no_network(monkeypatch):
 def refuse(*a,**kw):raise AssertionError("network disabled in documentation verification")
 monkeypatch.setattr(socket.socket,"connect",refuse)
 monkeypatch.setattr(socket.socket,"connect_ex",refuse)
 monkeypatch.setattr(socket,"getaddrinfo",refuse)
