import json

import pytest

import main


class FakeSignal:
    """Stand-in for psygnal.Signal: synchronous connect/emit, no threading."""

    def __init__(self):
        self._slots = []

    def connect(self, fn):
        self._slots.append(fn)

    def disconnect(self, fn):
        if fn in self._slots:
            self._slots.remove(fn)

    def emit(self, *args):
        for slot in list(self._slots):
            slot(*args)


class FakeUDPSocket:
    """Stand-in for helper_udp.UDPSocketClass with no real sockets/threads."""

    def __init__(self, recv_port=0):
        self.recv_port = recv_port
        self.own_public_key = "fake-own-pub-key"
        self.udp_recv_data = FakeSignal()
        self.peers = []
        self.sent = []
        self.stopped = False

    def add_peer(self, addr):
        ip, port = addr[0], addr[1]
        key = addr[2] if len(addr) == 3 else None
        for i, existing in enumerate(self.peers):
            if existing[0] == ip and existing[1] == port:
                if key:
                    self.peers[i] = (ip, port, key)
                return
        self.peers.append((ip, port, key) if key else (ip, port))

    def has_peer(self, addr):
        return any(p[0] == addr[0] and p[1] == addr[1] for p in self.peers)

    def send_data(self, data, addr=None):
        self.sent.append((data, addr))

    def stop(self):
        self.stopped = True


class FakePublisher:
    def __init__(self, *args, **kwargs):
        self.message = None
        self.started = False
        self.stopped = False

    def update_message(self, message):
        self.message = message

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class FakeListener:
    def __init__(self, *args, **kwargs):
        self.recv_signal = FakeSignal()
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


@pytest.fixture
def patched_network(monkeypatch):
    """Replace the network backends with in-memory fakes for isolated tests."""
    monkeypatch.setattr(main.helper_udp, "UDPSocketClass", FakeUDPSocket)
    monkeypatch.setattr(main.helper_multicast, "VaultMultiPublisher", FakePublisher)
    monkeypatch.setattr(main.helper_multicast, "VaultMultiListener", FakeListener)
    monkeypatch.setattr(main.helper_ip, "get_ip_addresses", lambda: (["192.0.2.1"], []))


@pytest.fixture
def nm(patched_network):
    return main.NetworkManager("Alice")


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def test_init_builds_multicast_announcement(nm):
    assert nm.mc_msg["name"] == "Alice"
    assert nm.mc_msg["key"] == nm.udp.own_public_key
    assert nm.mc_msg["type"] == "pong"
    assert nm.mc_msg["addr"] == (nm.ip, nm.port)
    assert nm.ip == "192.0.2.1"


def test_init_falls_back_to_localhost_without_ipv4(patched_network, monkeypatch):
    monkeypatch.setattr(main.helper_ip, "get_ip_addresses", lambda: ([], []))
    manager = main.NetworkManager("Bob")
    assert manager.ip == "127.0.0.1"


# ---------------------------------------------------------------------------
# update_opponent_ip
# ---------------------------------------------------------------------------

def test_update_opponent_ip_with_key_pre_seeds_peer(nm):
    addr = ("198.51.100.1", 4000)
    nm.update_opponent_ip(addr, "peer-key")

    assert nm.addr_opponent == addr
    assert nm.udp.peers == [(addr[0], addr[1], "peer-key")]


def test_update_opponent_ip_without_key_adds_new_peer(nm):
    addr = ("198.51.100.2", 4001)
    nm.update_opponent_ip(addr)

    assert nm.addr_opponent == addr
    assert nm.udp.has_peer(addr)


def test_update_opponent_ip_without_key_skips_known_peer(nm):
    addr = ("198.51.100.3", 4002)
    nm.udp.add_peer(addr)

    nm.update_opponent_ip(addr)

    assert nm.udp.peers.count((addr[0], addr[1])) == 1


# ---------------------------------------------------------------------------
# _handle_multicast_message
# ---------------------------------------------------------------------------

def _multicast_msg(nm, **overrides):
    msg = {
        "addr": ("203.0.113.5", 5000),
        "name": "Bob",
        "key": "bobs-key",
        "type": nm.sd_type,
    }
    msg.update(overrides)
    return msg


def test_handle_multicast_message_ignores_own_announcement(nm):
    found = []
    nm.bind(on_opponent_found=lambda inst, msg: found.append(msg))

    nm._handle_multicast_message(_multicast_msg(nm, name="Alice"))

    assert found == []
    assert nm.addr_opponent is None


def test_handle_multicast_message_ignores_other_service_types(nm):
    nm._handle_multicast_message(_multicast_msg(nm, type="not-pong"))
    assert nm.addr_opponent is None


def test_handle_multicast_message_without_key_is_ignored(nm):
    msg = _multicast_msg(nm)
    del msg["key"]

    nm._handle_multicast_message(msg)

    assert nm.addr_opponent is None


@pytest.mark.parametrize("bad_addr", [None, "203.0.113.5", ["203.0.113.5"], ("a", "b", "c")])
def test_handle_multicast_message_with_malformed_addr_does_not_raise(nm, bad_addr):
    nm._handle_multicast_message(_multicast_msg(nm, addr=bad_addr))

    assert nm.addr_opponent is None


def test_handle_multicast_message_happy_path(nm):
    found = []
    nm.bind(on_opponent_found=lambda inst, msg: found.append(msg))

    nm._handle_multicast_message(_multicast_msg(nm))

    assert nm.addr_opponent == ("203.0.113.5", 5000)
    assert nm.udp.peers == [("203.0.113.5", 5000, "bobs-key")]
    assert found == [{"name": "Bob"}]
    assert nm.publisher.stopped is True

    # An "init" message should have gone out over the (fake) UDP socket.
    assert len(nm.udp.sent) == 1
    sent_msg = json.loads(nm.udp.sent[0][0])
    assert sent_msg["init"]["name"] == "Alice"
    assert sent_msg["init"]["enc_key"] == nm.udp.own_public_key


# ---------------------------------------------------------------------------
# _handle_udp_data
# ---------------------------------------------------------------------------

def test_handle_udp_data_accepts_bytes_and_str(nm):
    updates = []
    nm.bind(on_game_data_update=lambda inst, data: updates.append(data))

    nm._handle_udp_data(json.dumps({"pad_pos": [1, 2]}), ("10.0.0.1", 1))
    nm._handle_udp_data(json.dumps({"pad_pos": [3, 4]}).encode("utf-8"), ("10.0.0.1", 1))

    assert updates == [{"pad_pos": [1, 2]}, {"pad_pos": [3, 4]}]


def test_handle_udp_data_dispatches_known_event(nm):
    scores = []
    nm.bind(on_score_update=lambda inst, data: scores.append(data))

    nm._handle_udp_data(json.dumps({"score_pl1": 3}), ("10.0.0.1", 1))

    assert scores == [{"score_pl1": 3}]


def test_handle_udp_data_ignores_unknown_key(nm):
    updates = []
    nm.bind(on_game_data_update=lambda inst, data: updates.append(data))

    nm._handle_udp_data(json.dumps({"mystery": 1}), ("10.0.0.1", 1))

    assert updates == []


def test_handle_udp_data_invalid_json_does_not_raise(nm):
    nm._handle_udp_data("not json", ("10.0.0.1", 1))


@pytest.mark.parametrize("payload", ["[1, 2, 3]", "5", '"just a string"'])
def test_handle_udp_data_non_object_payload_does_not_raise(nm, payload):
    nm._handle_udp_data(payload, ("10.0.0.1", 1))


def test_handle_udp_data_malformed_init_does_not_raise(nm):
    inits = []
    nm.bind(on_game_init=lambda inst, data: inits.append(data))

    nm._handle_udp_data(json.dumps({"init": "not-an-object"}), ("10.0.0.1", 1))

    assert inits == []
    assert nm.addr_opponent is None


def test_handle_udp_data_init_message_updates_opponent_and_dispatches(nm):
    inits = []
    nm.bind(on_game_init=lambda inst, data: inits.append(data))

    payload = {
        "init": {
            "ip": "10.0.0.2",
            "port": 6000,
            "enc_key": "opponent-key",
            "name": "Carol",
        }
    }
    nm._handle_udp_data(json.dumps(payload), ("10.0.0.2", 6000))

    assert nm.addr_opponent == ("10.0.0.2", 6000)
    assert nm.udp.peers == [("10.0.0.2", 6000, "opponent-key")]
    assert inits == [payload["init"]]


# ---------------------------------------------------------------------------
# send_game_data
# ---------------------------------------------------------------------------

def test_send_game_data_without_opponent_does_not_send(nm):
    nm.send_game_data({"pause": True})
    assert nm.udp.sent == []


def test_send_game_data_with_opponent_sends_json(nm):
    nm.addr_opponent = ("10.0.0.3", 7000)

    nm.send_game_data({"pause": True})

    assert len(nm.udp.sent) == 1
    data, addr = nm.udp.sent[0]
    assert json.loads(data) == {"pause": True}
    assert addr == ("10.0.0.3", 7000)


# ---------------------------------------------------------------------------
# Search lifecycle / cleanup
# ---------------------------------------------------------------------------

def test_start_and_stop_search_for_opponent(nm):
    nm.start_search_for_opponent()
    assert nm.publisher.started is True
    assert nm.listener.started is True

    nm.stop_search_for_opponent()
    assert nm.publisher.stopped is True
    assert nm.listener.stopped is True


def test_cleanup_stops_udp_socket(nm):
    nm.start_search_for_opponent()
    nm.cleanup()
    assert nm.udp.stopped is True
