# Networked Pong

A two-player Pong game built with Kivy. It communicates over encrypted UDP
and finds opponents via multicast.

This project exists mainly to demonstrate two libraries maintained by the
same author, included as submodules under `include/`:

- `include/udp` (py-vault-udp): encrypted, rate-limited UDP transport
- `include/multicast` (py-vault-multicast): multicast-based peer discovery

The game logic itself is intentionally simple; the point is exercising the
two libraries' APIs in a working, if minimal, application.

## Architecture

```
┌─────────────────────────────────────┐
│         Pong Game (Kivy)            │
├─────────────────────────────────────┤
│      NetworkManager (Events)        │
├─────────────────────────────────────┤
│  Multicast Discovery │ UDP Socket   │
├──────────────────────┼──────────────┤
│  VaultMulticast      │ VaultUDP     │
│  - Publisher         │ - Encryption │
│  - Listener          │ - Compression│
└─────────────────────────────────────┘
```

### Components

1. **NetworkManager**: wires network events to the game
2. **VaultUDPSocket**: encrypted, compressed UDP transport
3. **VaultMulticast**: peer discovery via multicast announcements
4. **Encryption**: NaCl SealedBox (anonymous, unauthenticated — see
   [Security Considerations](#security-considerations))

## Installation

### Requirements

- Python 3.10 - 3.12 (Kivy has no working wheels for newer versions yet)
- Kivy 2.2.0+

### Install

```bash
pip install -e .
```

For linting, type checking, and tests, install the `dev` extra instead:

```bash
pip install -e ".[dev]"
```

## Project Structure

```
pong/
├── main.py                           # Game logic
├── pong.kv                           # Kivy UI definition
├── pyproject.toml
├── README.md
└── include/                          # Submodules
    ├── multicast/
    │   └── vault_multicast.py        # Multicast discovery
    └── udp/
        ├── vault_ip.py               # IP utilities
        ├── vault_udp_socket.py       # UDP socket wrapper
        ├── vault_udp_encryption.py   # Encryption manager
        └── vault_udp_socket_helper.py # Crypto primitives
```

## Usage

```bash
python main.py
```

### Game Flow

1. **Search**: the game looks for an opponent on the local network
   ("Searching for opponent...")
2. **Connection**: once a peer is found, keys are exchanged and addresses
   registered
3. **Synchronization**: both sides confirm readiness before starting
   ("Synchronizing...")
4. **Start**: after sync, the ball starts moving

### Controls

#### Keyboard
- `W` / `↑`: paddle up
- `S` / `↓`: paddle down
- `P`: pause/resume (after sync)
- `R`: reset (after game over)

#### Mouse
- Move the mouse within your control area to position the paddle
  - Left third of the screen: player 1
  - Right third of the screen: player 2

#### Mixed (default)
Both keyboard and mouse are active at the same time.

#### Buttons
- **Pause/Play**: toggles pause
- **Control Mode**: cycles mix → mouse → keyboard

### Message Types

Game messages (payload channel): `score_pl1`, `score_pl2`, `pad_pos`,
`ball_vel`, `ball_pos`, `pause`, `game_over`, `reset_scores`, `game_close`

Control messages (control channel): `init`, `sync_ready`, `sync_ack`,
`enc_key` (sent as part of `init`)

### Network Discovery

Peer discovery uses multicast on `224.1.1.1:5004`:

```python
{
    "addr": ["192.168.1.100", 15293],
    "name": "Dave_4630676",
    "key": "base64_encoded_public_key",
    "type": "pong"
}
```

## Configuration

### Game constants (in `main.py`)

```python
MAX_BALL_SPEED = 38           # Maximum ball velocity
POINTS_TO_WIN = 10            # Score needed to win
PADDLE_MOVE_SPEED = 80        # Paddle movement speed
BALL_START_SPEED = 6          # Initial ball speed
PADDLE_CONTROL_AREA_FACTOR = 1/3  # Mouse control zone
```

### Network defaults (in the `include/udp` and `include/multicast` submodules)

```python
DEFAULT_MULTICAST_GROUP = "224.1.1.1"
DEFAULT_PORT = 5004
DEFAULT_RATE_LIMIT = 100      # Messages per second per peer
DEFAULT_KEY_LIFETIME = 60     # Key lifetime in seconds
```

## Synchronization Protocol

A 3-way handshake before the game starts:

```
Player A                    Player B
   │                           │
   ├─── sync_ready ──────────► │
   │ ◄────── sync_ready ────────┤
   │                           │
   ├─── sync_ack ────────────► │
   │ ◄────── sync_ack ──────────┤
   │                           │
   GAME STARTS             GAME STARTS
```

This gives both sides a stable connection, exchanged keys, and a
simultaneous start.

## Game Owner

Ownership is decided deterministically to avoid conflicts:

```python
game_owner = (my_name < enemy_name)  # lexicographic comparison
```

The owner runs ball physics, collision detection, and score updates, and
sends authoritative state. The other side sends its paddle position,
applies received state, and can pause/unpause locally.

## Troubleshooting

### No opponent found

Likely causes: firewall blocking multicast (224.1.1.1:5004) or UDP
(random ports 2000-20000), or the two instances being on different
network segments.

```bash
# Linux: allow multicast
sudo iptables -A INPUT -p udp -d 224.1.1.1 --dport 5004 -j ACCEPT

# check multicast routing
ip maddr show
```

On Windows, check that Python is allowed through Windows Defender
Firewall.

### "No key for address, sending unencrypted"

Expected during initial discovery, before keys are exchanged. If it
persists, check that both clients use the same protocol version and
check the logs for key-exchange errors.

### Desynchronization

Press `P` to pause on both sides, then `R` to reset. If that doesn't
recover, restart both clients.

### High latency

Check for network congestion, packet loss, or CPU load. Reducing
`PADDLE_MOVE_SPEED` can help make lag less noticeable.

## Development

### Logging

```python
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

### Testing locally

Run two instances on the same machine; they discover each other over
multicast loopback.

```bash
python main.py   # terminal 1
python main.py   # terminal 2
```

Note: multicast does not work in every sandboxed/virtualized environment.
If discovery hangs in such an environment, that's the network setup, not
necessarily a code bug — verify on real hardware/network.

### Adding a message type

1. Add it to `event_map` in `NetworkManager.__init__()`:
```python
self.event_map = {
    "my_new_message": "on_game_status_update",
}
```
2. Handle it in the corresponding event handler:
```python
def on_game_status_update(self, instance, data):
    if "my_new_message" in data:
        ...
```
3. Send it from game logic:
```python
msg = {"my_new_message": my_value}
self.network.send_game_data(msg)
```

## Security Considerations

### Threat model

The transport uses NaCl **SealedBox**, which is anonymous, unauthenticated
encryption: it hides message contents from anyone without the recipient's
private key, but does not verify who sent a message.

**Covered**:
- Eavesdropping — SealedBox encryption hides message contents from an
  observer without the recipient's private key
- Rate-based DoS from a single peer — per-peer rate limiting

**Not covered**:
- Sender spoofing — anyone holding a peer's public key (broadcast openly
  via multicast) can send that peer validly-encrypted messages; there is
  no way to verify the actual sender
- Replay attacks — no nonce/timestamp tracking, so a captured ciphertext
  can be resent later and will decrypt again
- Man-in-the-middle during key exchange — public keys are exchanged in
  the clear on first contact with no signing or verification
- Network-level DoS, physical access to the machine, or a compromised
  Python environment

Given this, treat the game as suitable for a trusted LAN among people who
already trust each other, not as a hardened protocol for hostile
networks.

### Practices

- Run on trusted networks only
- Keep dependencies updated
- Restrict UDP ports via firewall if exposed beyond a LAN

## License

Copyright 2025 ecki. Licensed under the Apache License, Version 2.0.

## Contributing

This is a personal project; suggestions are welcome via issues.

Code style: PEP 8, type hints where useful, logging over print for
diagnostics.

## Credits

Author: ecki

Dependencies: [Kivy](https://kivy.org/), [PyNaCl](https://pynacl.readthedocs.io/),
[msgpack](https://msgpack.org/), [zstd](https://facebook.github.io/zstd/)

## Changelog

### 2.1 (current)
- Switched the transport to NaCl SealedBox (anonymous, unauthenticated —
  see [Security Considerations](#security-considerations))
- Added ruff/mypy/pytest tooling and CI for the main game code
- Fixed a reconnect bug where rejoining a game scheduled the update loop
  multiple times
- Fixed the ball not re-serving on a peer that didn't trigger a score
  reset

### 2.0
- Structured protocol v2
- Added a synchronization phase before game start
- Deterministic game owner selection
- Key exchange with signatures
- Replay attack mitigation, per-peer rate limiting

### 1.0
- Initial release: basic multiplayer Pong over UDP with multicast
  discovery

## Ideas / not done

- Spectator mode
- IPv6 support
