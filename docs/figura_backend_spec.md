# Figura self-hosted backend on `minecraft_backend`

Goal: replace CPM/`voidrp-cpm-companion` with **Figura** (client mod, 1.21.1 NeoForge) and host
the **Figura backend ourselves on our FastAPI** so the server controls avatars (grant / sell /
revoke cosmetics). Reverse-engineered from the Figura 1.21 client (`common/.../backend2/*`).

## How Figura's backend works (client expectations)

Client config `Configs.SERVER_IP` → base URL `https://<SERVER_IP>[:port]/api`. Every HTTP request
carries header `token: <token>`. WebSocket for live avatar distribution.

### Auth (2-step, Mojang-based — needs patch for offline)
1. `GET /api/auth/id?username=<name>` → returns a `serverID` string.
2. Client calls Mojang `joinServer(uuid, accessToken, serverID)` — **fails for offline players**.
3. `GET /api/auth/verify?id=<serverID>` → returns the session `token`.

**Offline fix:** we build Figura from source, so patch `AuthHandler.auth()` to skip the Mojang
`joinServer` and get a token from our backend keyed to the launcher-authenticated identity
(reuse the play-ticket / a per-session token). Backend `/auth/verify` then trusts it.

### HTTP API (`/api`, `token` header)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | 200 OK iff token valid (checkAuth) |
| GET | `/auth/id?username=` | step-1 serverID |
| GET | `/auth/verify?id=` | step-2 token |
| GET | `/limits` | JSON: avatar size / rate limits |
| GET | `/version` | version/allowed-versions JSON |
| GET | `/motd` | MOTD string |
| GET | `/<uuid>` | user info: equipped avatars list + badges |
| GET | `/<owner_uuid>/<avatarId>` | avatar bytes (the .moon/nbt blob) |
| PUT | `/<avatarId>` (octet-stream) | upload avatar for the authed user |
| DELETE | `/<avatarId>` | delete avatar |
| POST | `/equip` (json) | set the authed user's equipped avatars |

### WebSocket (binary, first byte = message id)
Client→server (`C2SMessageHandler`): `TOKEN=0`+utf8 token, `PING=1`, `SUB=2`+uuid(16B),
`UNSUB=3`+uuid. Client subscribes to nearby players' UUIDs.
Server→client (`S2CMessageHandler`): `AUTH`, `PING=1`, `EVENT=2`(+uuid → "that user changed,
re-fetch their avatar over HTTP"), `TOAST=3`, `CHAT=4`, `NOTICE=5`.
So avatar BYTES flow over HTTP; the WS only pushes "user X changed" so subscribers re-`GET`.

## Server-controlled cosmetics (the whole point)
Since we own the backend, "grant a cosmetic to a player" = store an avatar we authored and set it
as that player's equipped avatar (the client fetches + renders it). Others see it because they're
subscribed over the WS and re-fetch on the `EVENT`. This is the 1.21 replacement for the old
≤1.20 `/fsb avatar set` command.

**Slots (like CPM):** a player's rendered avatar is ONE Figura avatar. To combine head/body/wings
cosmetics, compose a per-player avatar on the fly from the equipped-slot parts (Blockbench parts
recognised: HEAD/BODY/LEFT_ARM/RIGHT_ARM/…/cape) and store it as their equipped avatar. Backend
owns the compositor; equipping a slot recomposes + bumps the version → WS EVENT → everyone updates.

## Implementation plan (on minecraft_backend)
1. **Infra:** subdomain `figura.void-rp.ru` → nginx → backend; the client path is fixed to `/api/*`
   so we serve the Figura router at `/api` on that vhost (not under `/api/v1`).
2. **Models:** `figura_avatars` (owner_uuid, avatar_id, data bytes/path, hash, version, size),
   `figura_equipped` (owner_uuid → list of avatar ids), `figura_tokens` (session token → uuid/name).
   Cosmetics catalog + per-player ownership reuse the existing cosmetics tables later.
2b. **HTTP router** (`routes/figura.py`): all endpoints above.
3. **WebSocket** (`/api/ws` or `/ws`): binary protocol, sub/unsub registry, EVENT fan-out.
4. **Client patch** (build from `Figura/` source, branch `1.21`): offline auth in `AuthHandler`;
   default `SERVER_IP` = our host baked into the pack config. Fix build: architectury snapshot
   repo missing — add `maven { url "https://maven.architectury.dev/" }` / pin a resolvable version.
5. **Cosmetics:** author avatars (Blockbench → Figura .moon), backend compositor per slot, admin
   grant + (later) purchase with Void Coins, `/vcosmetic` command.

## Status
Spec captured (protocol reverse-engineered). Client source builds are gated by the architectury
snapshot repo (fixable). Nothing implemented yet — next: infra decision (subdomain) + backend
Figura router skeleton (auth/version/motd/limits testable via curl), then avatars + WS.
