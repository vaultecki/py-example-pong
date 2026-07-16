# Networked Pong Game

A peer-to-peer multiplayer Pong game built with Kivy, featuring encrypted UDP communication, automatic peer discovery via multicast, and synchronized gameplay.

## Features

- 🎮 **Classic Pong Gameplay**: Two-player competitive Pong
- 🔍 **Automatic Peer Discovery**: Multicast-based opponent finding
- 🔄 **Synchronized Start**: Both players must be ready before game begins
- 🎯 **Multiple Control Modes**: Mouse, keyboard, or mixed controls
- 🚀 **Low Latency**: Compressed, MTU-padded UDP protocol
- 📊 **Score Tracking**: First to 10 points wins

## Architecture

### Network Stack

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

### Key Components

1. **NetworkManager**: Handles all network communication and events
2. **VaultUDPSocket**: Encrypted, compressed UDP communication
3. **VaultMulticast**: Peer discovery via multicast announcements
4. **Encryption Module**: NaCl SealedBox (anonymous, unauthenticated encryption -- see [Security Considerations](#security-considerations))

## Installation

### Requirements

- Python 3.10 - 3.12 (Kivy does not yet ship working wheels for newer versions)
- Kivy 2.2.0+

### Install Dependencies

```bash
pip install -e .
```

For linting, type checking, and running the tests, install the `dev` extra instead:

```bash
pip install -e ".[dev]"
```

## Project Structure

```
pong/
├── main.py                           # Main game logic
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

### Starting the Game

```bash
python main.py
```

### Game Flow

1. **Search Phase**: Game automatically searches for opponents on local network
   - Status: "Searching for opponent..."
   
2. **Connection Phase**: When opponent found, automatic key exchange begins
   - UDP encryption keys are exchanged
   - Peer addresses are registered
   
3. **Synchronization Phase**: Both players synchronize before start
   - Status: "Synchronizing..."
   - Ensures both clients are ready
   
4. **Game Start**: After successful sync
   - Status: "READY!" (briefly)
   - Game begins, ball starts moving

### Controls

#### Keyboard Mode
- `W` / `↑`: Move paddle up
- `S` / `↓`: Move paddle down
- `P`: Pause/Resume (after sync)
- `R`: Reset game (after game over)

#### Mouse Mode
- Move mouse in your control area to position paddle
  - Left third of screen: Player 1
  - Right third of screen: Player 2

#### Mixed Mode (Default)
- Both keyboard and mouse controls active

### Game Controls (Buttons)

- **Pause/Play**: Toggle game pause
- **Control Mode**: Cycle through control modes (mix → mouse → keyboard)


### Message Types

#### Game Messages (Payload Channel)
- `score_pl1`, `score_pl2`: Score updates
- `pad_pos`: Paddle position
- `ball_vel`, `ball_pos`: Ball state
- `pause`: Pause state
- `game_over`: Game end notification
- `reset_scores`: Score reset
- `game_close`: Opponent disconnected

#### Control Messages (Control Channel)
- `init`: Initial connection setup
- `sync_ready`: Player ready for synchronization
- `sync_ack`: Synchronization acknowledgment
- `enc_key`: Public key exchange (sent as part of the `init` message)

### Security Features

1. **Anonymous Encryption**: NaCl SealedBox (X25519 + XSalsa20 + Poly1305) -- see [Security Considerations](#security-considerations) for what this does *not* protect against
2. **Compression**: zstd for all payloads
3. **Rate Limiting**: 100 messages/second per peer
4. **Key Lifecycle**: Automatic key rotation and expiry

### Network Discovery

The game uses multicast (224.1.1.1:5004) for peer discovery:

```python
{
    "addr": ["192.168.1.100", 15293],
    "name": "Dave_4630676",
    "key": "base64_encoded_public_key",
    "type": "pong"
}
```

## Configuration

### Game Constants

Edit these in `main.py`:

```python
MAX_BALL_SPEED = 38           # Maximum ball velocity
POINTS_TO_WIN = 10            # Score needed to win
PADDLE_MOVE_SPEED = 80        # Paddle movement speed
BALL_START_SPEED = 6          # Initial ball speed
PADDLE_CONTROL_AREA_FACTOR = 1/3  # Mouse control zone
```

### Network Configuration

```python
DEFAULT_MULTICAST_GROUP = "224.1.1.1"
DEFAULT_PORT = 5004
DEFAULT_RATE_LIMIT = 100      # Messages per second
DEFAULT_KEY_LIFETIME = 60     # Key lifetime in seconds
```

## Synchronization Protocol

The game uses a 3-way handshake for synchronization:

```
Player A                    Player B
   │                           │
   ├─── sync_ready ──────────► │
   │ ◄────── sync_ready ────────┤
   │                           │
   ├─── sync_ack ────────────► │
   │ ◄────── sync_ack ──────────┤
   │                           │
   ✓ GAME STARTS          ✓ GAME STARTS
```

This ensures:
- Both players have stable connections
- Encryption keys are exchanged
- Game state is ready on both sides
- Fair simultaneous start

## Game Owner Logic

To prevent conflicts, game ownership is determined deterministically:

```python
game_owner = (my_name < enemy_name)  # Lexicographic comparison
```

The game owner:
- Controls ball physics (authoritative)
- Sends score updates
- Handles collision detection
- Synchronizes ball position

The client:
- Sends paddle position
- Receives and displays ball/score state
- Can pause/unpause locally

## Troubleshooting

### No Opponent Found

**Causes**:
- Firewall blocking multicast (224.1.1.1:5004)
- Firewall blocking UDP (random ports 2000-20000)
- Different network segments

**Solutions**:
```bash
# Linux: Allow multicast
sudo iptables -A INPUT -p udp -d 224.1.1.1 --dport 5004 -j ACCEPT

# Windows: Allow Python through firewall
# Check Windows Defender Firewall settings

# Check multicast routing
ip maddr show  # Linux
```

### "No key for address, sending unencrypted"

This is normal during initial discovery. Keys are exchanged after connection.

If it persists:
- Check that both clients are using the same protocol version
- Verify encryption keys are being exchanged in init messages
- Check logs for key exchange errors

### Desynchronization

If game becomes desynchronized:
- Press `P` to pause on both sides
- Press `R` to reset
- Or close and restart both clients

### High Latency

**Causes**:
- Network congestion
- High packet loss
- CPU load

**Solutions**:
- Reduce `PADDLE_MOVE_SPEED` for smoother play
- Check network quality with `ping`
- Close other network-heavy applications

## Development

### Logging

Enable debug logging:

```python
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

### Testing Locally

Run two instances on the same machine:

```bash
# Terminal 1
python main.py

# Terminal 2
python main.py
```

They will discover each other via multicast loopback.

### Adding New Message Types

1. Add to `event_map` in `NetworkManager.__init__()`:
```python
self.event_map = {
    "my_new_message": "on_game_status_update",
}
```

2. Handle in appropriate event handler:
```python
def on_game_status_update(self, instance, data):
    if "my_new_message" in data:
        # Handle it
        pass
```

3. Send from game logic:
```python
msg = {"my_new_message": my_value}
self.network.send_game_data(msg)
```

## Performance

### Optimization Tips

1. **Paddle Updates**: Only sent when position changes
2. **Ball Updates**: Only sent by game owner
3. **Compression**: zstd level 16 for all payloads
4. **MTU Padding**: Prevents packet fragmentation

## Security Considerations

### Threat Model

The transport uses NaCl **SealedBox**, which is anonymous, unauthenticated
encryption: it hides message contents from anyone without the recipient's
private key, but it does not verify who sent a message.

**Protected Against**:
- ✅ Eavesdropping (SealedBox encryption -- an observer without the recipient's private key can't read message contents)
- ✅ Rate-based DoS (per-peer rate limiting)

**Not Protected Against**:
- ❌ Sender spoofing (anyone holding a peer's public key -- which is broadcast openly via multicast -- can send that peer validly-encrypted messages; there is no way to verify who actually sent a given message)
- ❌ Replay attacks (no nonce/timestamp tracking -- a captured ciphertext can be resent later and will decrypt successfully again)
- ❌ Man-in-the-middle during key exchange (public keys are exchanged in the clear on first contact with no signing or verification; an attacker present from the start of a session could substitute their own key unnoticed)
- ❌ Network-level DoS (use firewall)
- ❌ Physical access to machine
- ❌ Compromised Python environment

Given all of this, treat the game as suitable for a trusted LAN among people
who already trust each other -- not as a hardened protocol for hostile
networks.

### Best Practices

1. Run on trusted networks only
2. Keep dependencies updated
3. Use firewall to restrict UDP ports
4. Monitor logs for suspicious activity

## License

Copyright [2025] [ecki]

Licensed under the Apache License, Version 2.0

## Contributing

This is a personal project, but suggestions are welcome via issues.

### Code Style

- PEP 8 compliance
- Type hints where beneficial
- Docstrings for public methods
- Logging for debugging

## Credits

**Author**: ecki

**Technologies**:
- [Kivy](https://kivy.org/) - UI framework
- [PyNaCl](https://pynacl.readthedocs.io/) - Cryptography
- [msgpack](https://msgpack.org/) - Serialization
- [zstd](https://facebook.github.io/zstd/) - Compression

## Changelog

### Version 2.1 (Current)
- Switched the transport to NaCl SealedBox (anonymous, unauthenticated encryption -- see [Security Considerations](#security-considerations))
- Added ruff/mypy/pytest tooling and CI for the main game code
- Fixed a reconnect bug where rejoining a game would schedule the update loop multiple times
- Fixed the ball not re-serving on a peer that didn't trigger a score reset

### Version 2.0
- Upgraded to Protocol v2 with structured format
- Added synchronization phase before game start
- Deterministic game owner selection
- Improved key exchange with signatures
- Enhanced replay attack prevention
- Rate limiting per peer

### Version 1.0
- Initial release
- Basic multiplayer Pong
- UDP communication
- Multicast discovery

## Future Ideas

- [ ] Spectator mode
- [ ] IPv6 support

---

**Enjoy the game! 🏓**