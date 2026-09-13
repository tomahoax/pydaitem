# Daitem Secure API reference

Facts below describe the current behaviour of the API; anything not established is marked
as such rather than guessed.

No real secret appears here: tokens, alarm codes, serial numbers and personal identifiers
are replaced by `<...>` placeholders.

## Overview

- **Auth**: Keycloak / OpenID Connect at `auth.atraltech.com`, realm `daitem`.
- **Business API**: "Topaze" platform at `appv3.tt-monitor.com`, prefix `/topaze/`,
  authenticated with `Authorization: Bearer <access token>`.
- **No request signature or verified timestamp.** Only the bearer and a couple of headers.
- **`systemId`** is the thread running through the whole API.

### Required headers

| Header | Required? | Value constrained? |
|--------|-----------|--------------------|
| `Authorization` | Yes | Valid bearer |
| `X-App-Name` | **Yes, everywhere** | **Yes: `eNova`** |
| `X-App-Version` | **Yes for `connect`** (optional for reads) | No, free |
| `X-App-Platform` | No | No |
| `User-Agent` | No | No, entirely free |

- `X-App-Name` missing -> `400` from the **Azure App Service** gateway; the request never
  reaches the Topaze API. It is a **product routing key**, not a client identity: any value
  other than `eNova` reaches the app but returns `500 {"message":null}`.
- `X-App-Version` missing on `connect` -> `400` from the gateway, while read endpoints
  (`/v1/user`, `/v5/systems`, `/v2/.../configuration`) succeed without it.
- `X-App-Platform` and `User-Agent` are entirely free-form, so a client can identify itself
  honestly instead of impersonating the mobile app; only `X-App-Name: eNova` must be kept
  as-is, for routing.

### Other hosts contacted by the app, unrelated to alarm control

`ota.lokalise.co` (OTA translations) and `*.ingest.sentry.io` (crash reporting).

---

## 0. Login (Keycloak, OAuth2 authorization_code + PKCE)

Full flow, base `https://auth.atraltech.com`, realm `daitem`:

1. **Login page**: `GET /realms/daitem/protocol/openid-connect/auth` with
   `response_type=code`, `code_challenge=<...>`, `code_challenge_method=S256`,
   `client_id=daitem-secure-app`, `redirect_uri=daitemsecure://auth`. Returns the Keycloak
   HTML page and sets an auth session cookie.
2. **Credential submission**: `POST /realms/daitem/login-actions/authenticate?...`
   (form-urlencoded: `username`, `password`, `credentialId`) -> `302` to
   `daitemsecure://auth?session_state=...&iss=...&code=<CODE>`. The code is in the
   `Location` header.
3. **Code exchange**, below.

- **Token endpoint**: `POST /realms/daitem/protocol/openid-connect/token`
- **Body** (form-urlencoded):
  ```
  client_id=daitem-secure-app
  grant_type=authorization_code
  code=<code from the Location header>
  code_verifier=<PKCE verifier>
  redirect_uri=daitemsecure://auth
  ```
- **Response**: `access_token` (RS256 JWT), `refresh_token`, `token_type=Bearer`,
  `session_state`.
- **JWT**: `iss=https://auth.atraltech.com/realms/daitem`, `aud=["atraltech","account"]`,
  `azp=daitem-secure-app`. **Access token lifetime: 1800 s (30 min)** (`exp - iat`).
- **Refresh**: `grant_type=refresh_token` + `client_id`. A later JWT shows an advanced
  `iat` while `auth_time` is unchanged, which is how the refresh renews the access token
  without a new login. A replayed expired refresh token returns
  `400 {"error":"invalid_grant","error_description":"Token is not active"}`.
- **Logout**: `POST /realms/daitem/protocol/openid-connect/logout` -> `204`.
- **Headless clients**: the `password` grant (ROPC) is **refused** by the realm. The
  `authorization_code` + PKCE flow works headless instead: generate a PKCE pair, GET
  `auth` (keep cookies and the form action), POST credentials to
  `login-actions/authenticate`, extract the `code` from `Location`, exchange it. The
  anti-bot script Keycloak also serves on the auth domain (paths `bnith__<base64>`) does
  not block a direct form POST; it would only matter to a headless-browser automation.

## 1. User profile

`GET /topaze/v1/user`

```json
{"userId":<int>,"userUid":"<uuid>","username":"<email>","firstName":"<...>","lastName":"<...>"}
```

## 2. Listing and selecting a system

- `GET /topaze/v5/systems`
  ```json
  [{"id":<systemId>,"vendor":"edaitem","name":"<site name>","role":1}]
  ```
  `role` is the calling account's role: `1` owner, `0` restricted user.
- **Selection: no dedicated call.** There is no "select" endpoint. Selection is entirely
  client-side: pick an `id` and reuse it as `<systemId>` in every later URL.
- A flag `isFavoritesMigrationPopupShown` hints at a favourite-system notion in the app,
  but no favourites endpoint is documented here.

## 3. System configuration (legacy)

`POST /topaze/configuration/getConfiguration`, body `{"role":1,"systemId":<systemId>}`

```json
{"transmitterId":"<hex>","centralId":"<hex>","installationComplete":true,
 "name":"<name>","role":1,"rights":{},"id":<systemId>,"standalone":false,"gprsPhone":null}
```

Gives `transmitterId` (transmission module) and `centralId` (panel), reused later. These
are hardware identifiers, not commercial references.

## 4. Installation connectivity

`POST /topaze/installation/isConnected`, body `{"transmitterId":"<hex>"}` ->
`{"isConnected":true}`

## 5. Opening the panel session (connect)

- `POST /topaze/v5/systems/<systemId>/connect`, body `{"masterCode":"<alarm code>"}`
- **Response**:
  ```json
  {"message":null,"ttmSessionId":"<hex>","systemState":"off",
   "groups":[],"groupList":[{"id":1,"active":false},{"id":2,"active":false}],
   "status":"OK","versions":{"box":"7.8.4"},
   "connectedUserType":"OWNER","codeIndex":null,
   "userRightsConfiguration":{"alarms":{},"videos":{}}}
  ```
- **Connection code**: a restricted account's `connect` is accepted with **that account's
  own code** (not the owner's master code), returning `connectedUserType:"RESTRICTED"`.

### One session at a time, per panel rather than per account

The lock is per panel, not per account: a session held by one account blocks `connect` for
any other account on the same panel, even across two entirely distinct accounts. A second
`connect` while one is already open returns:

```
409 {"message":"transmitter.connection.sessionalreadyopen","details":"owner "}
```

`details` names the holder. A secondary account does not solve control concurrency: any two
clients (a phone and an integration, for instance) contend for the single transmitter
session.

Consequences for a client:

- **Reading** works while *any* TTM session exists, whoever holds it. If another device is
  connected, a client can read without opening its own. With nobody connected, `get_state`
  fails and a client must `connect` itself, which puts it in contention.
- **Commands** need an open session regardless. Open `connect` right before a command,
  tolerate the `409`, release with `disconnect`.

### Closing the session (disconnect)

`POST /topaze/v5/systems/<systemId>/disconnect`, body `{"force": false}` ->
`{"status":"OK"}`. The body is required; without it the API returns `400 bad request body`.

## 6. Arming and disarming

### Whole system

- `POST /topaze/v1/action/systems/<systemId>/sendSystemCommand`
- **Arm**: `{"active": true}` — **Disarm**: `{"active": false}`
- **Response** (same schema as `/state`):
  ```json
  {"message":null,"systemState":"tempo","groups":[{"id":1,"active":true},{"id":2,"active":true}],
   "defaults":"010000","commandStatus":"CMD_OK","openedIssueNumbers":[]}
  ```
- `commandStatus:"CMD_OK"` means the panel accepted the command.
- `defaults` is a six-digit string of unknown meaning. Seen as `000000` (disarmed) and
  `010000` (armed): possibly a state or group mask, not documented further here.

### Partial arming (presence preset)

`POST /topaze/v1/action/systems/<systemId>/startPartialArmingWidgetCommand/<presetIndex>`
(no body). For example, index `0` can map to `systemState:"presence"`, with one group
active and another not, depending on how the preset is configured.

### Per-group arming and disarming

- `POST /topaze/v1/action/systems/<systemId>/sendGroupCommand`
- **Body**: `{"groups":[{"id":1,"active":true}]}`; several groups can be driven at once.
- **Arming**: `systemState:"tempogroup"` then `"group"`.
- **Disarming**: `{"groups":[{"id":1,"active":false}]}` -> `"off"` immediately, with no
  delay.
- This is the finest-grained primitive, and the one to use for per-group control.

## 7. System state

`GET /topaze/v5/systems/<systemId>/state`, same schema as the command responses.

**`systemState` values:**

| Value | Meaning |
|-------|---------|
| `off` | Disarmed |
| `tempo` | Exit delay, full arming |
| `on` | Fully armed |
| `presence` | Partial arming via widget preset |
| `tempogroup` | Exit delay for group arming |
| `group` | Group(s) armed |
| (triggered) | Unknown |

Two distinct forms of partial arming coexist: `presence` (a named preset) and `group`
(direct group activation), with the same group split but a different `systemState`.

**Session prerequisite**: `get_state` needs a TTM session open on the transmitter, held by
any device. Two distinct errors signal an unusable session, with the same remedy
(`connect`):

- `500 {"message":"status.nottmsessionid","details":"Failed to get last TTM session"}`:
  no session at all.
- `500 {"message":"transmitter.error.invalidsessionid","details":"Invalid session id: <hex>"}`:
  a session exists but its id is **stale** — the shape left by a previous session that ended
  without a clean `disconnect`.

**App behaviour**: polls at roughly 1 Hz during a delay, until the state settles.

## 8. System users

`GET /topaze/v5/systems/<systemId>/users` -> `owner` plus `restrictedUsers[]`, each with
per-group `rights`, `userId` and `codeId` (`MS01` for the master, `RS<userId>` for a
restricted user). Contains personal data (address, third-party emails): never commit raw.

## 9. Device inventory

`GET /topaze/v2/systems/<systemId>/configuration` (~4.5 kB)

```json
{"isTlsEnabled":false,"isAlertEnabled":true,"isScenarioEnabled":true,
 "central":{"name":"","serialNumber":"<sn>","type":"INTRUSION","hasIO":true,
   "anomalies":{"mainPowerSupplyAlert":false,"secondaryPowerSupplyAlert":false,
                "defaultMediaAlert":true,"autoprotectionMechanicalAlert":false,
                "autoprotectionWiredAlert":false},
   "firmwareInfo":{"firmwares":[{"firmwareType":"SOFT","currentVersion":{"releaseVersion":"6.4.13"}}]},
   "plug":{"serialNumber":"<sn>"}},
 "box":null,"transmitters":[],"sirens":[],"transceivers":[],
 "genericSensors":{"sensors":[],"ppmsTriggers":[],"fireTriggers":[]},
 "commands":[]}
```

- `genericSensors.sensors[]`: one entry per detector, each with `index`, `name`,
  `serialNumber`, `type`, `group`, `isInhibitable`, `isInhibited`, `isVideo`, and
  `anomalies{powerSupplyAlert, autoprotectionMechanicalAlert, radioAlert, sensorAlert,
  loopAlert, maskAlert}`.
- `commands[]`: one entry per control device, each with `index`, `name`, `serialNumber`
  and `type` (seen as `REMOTE` and `DEFAULT`, for a remote and a keypad respectively).
- `central.hasIO:true` means the panel has a built-in I/O board.
- `central.anomalies.defaultMediaAlert:true` is very likely the red dot shown next to the
  panel name in the app.

### No live per-detector state

The API exposes identity, group, inhibition and **faults**, not the instantaneous contact
state: none of `state`, `isOpen`, `contact`, `triggered` or `value` appears on a sensor.
Two related limits:

- `type` is `DEFAULT` for every detector: the API does not distinguish door from window
  from motion; only the user-assigned `name` does.
- A door opening only appears in the **logbook**, as a timestamped event, while armed.

**Consequence**: each detector can become a device exposing **fault** binary sensors (low
battery, tamper, radio, masking) and an inhibition status, but not a real-time opening
contact. Only the wired I/O board route (out of scope here) would give that.

## 10. Feature discovery and command vocabulary

- `GET /topaze/v1/systems/<id>/cameras` -> `{"cameras":[]}`
- `GET /topaze/v6/systems/<id>/videos` -> `{"videos":[]}`
- `GET /topaze/v6/systems/<id>/scenarios` and `/scenarios/templates` -> empty
- `GET /topaze/v5/systems/<id>/scenarios/configuration` -> triggers `AUTO_FIRE`,
  `AUTO_INTRUSION`, `MANUAL` (max 18), delay 5–600 s in 5 s steps.
- `GET /topaze/v6/systems/<id>/scenarios/actions` -> **canonical alarm command vocabulary**:
  ```json
  {"actions":[{"type":"ALARM","commands":[
     {"id":"FULL_STOP"},{"id":"FULL_START"},{"id":"PRESENCE_START"},
     {"id":"PARTIAL_START_1"},{"id":"PARTIAL_START_2"}]}]}
  ```
  Two partial presets exist (`PARTIAL_START_1`/`_2` = `startPartialArmingWidgetCommand/0`
  and `/1`) alongside `PRESENCE_START`.
- `GET /topaze/v1/widgets/systems/<id>/users/<userId>` -> partial-arming widget
  configuration, mapping each item to its groups:
  `widgetItems[{id:0,name:"partial_arming_name_presence",groups:[1]}]`. The item `id` is
  the index passed to `startPartialArmingWidgetCommand/<index>`.
- `GET /topaze/v5/systems/<id>/automatisms` -> `{"automatisms":[]}`
- `GET /topaze/v5/upsell/fr`, `.../isFavoritesMigrationPopupShown`: cosmetic.

## 11. Schedules (scheduled arm/disarm)

Base `/topaze/v5/systems/<systemId>/schedule`. Recurring arming and disarming, per day and
per group.

- **List**: `GET .../schedule`
  ```json
  {"globalActivation":false,
   "programs":[{"id":1,"day":"monday","hour":22,"minute":0,"command":true,"groups":[1]}],
   "maxProgramCount":50}
  ```
  `command` is `true` for arming, `false` for disarming. `globalActivation` is the master
  switch. Up to 50 programs.
- **Update**: `PUT .../schedule/<programId>` with the full body -> returns the updated
  program (`200`).
- **Delete**: `DELETE .../schedule/<programId>` -> `204`.
- **Enable/disable all**: `PUT .../schedule/activate` with `{"activate": true|false}` ->
  `204`.
- **Create**: not documented here. Likely `POST .../schedule`, unconfirmed.

## 12. Session keep-alive

- `POST /topaze/authenticate/keepAlive` with `{"ttmSessionId":"<hex>"}` ->
  `{"message":null}`.
- The `ttmSessionId` from `connect` is not resent on ordinary calls (which carry only the
  bearer and `X-App-*` headers); it is used **here only**, to keep the panel session alive.
- The mobile app sends `keepAlive` roughly every 8 minutes after `connect`.
- Polling the state alone keeps the session alive without any `keepAlive` call: sessions
  stay open under a 60 s polling interval, stable for at least 20 minutes in that mode.
- The idle timeout with no polling at all — how long an orphaned session blocks other
  devices if a client stops without `disconnect` — is not documented here.

## 13. Alerts and notifications

Base `/topaze/v5/systems/<systemId>/notifications`.

- **Check a device**: `GET .../notifications/registered?pnsHandle=<APNs token>` ->
  `{"isRegistered":bool}`
- **Register for push**: `POST .../notifications` with
  `{"lang":"fr","deviceId":"<APNs token>","userAgent":"IPHONE"}` -> `204`
- **Read preferences**: `GET .../notifications` ->
  ```json
  [{"userIdentity":{"userId":0,"email":"<...>","firstName":"<...>","lastName":"<...>"},
    "userType":"OWNER",
    "alertConfigurationMail":{"notificationsMailIntrusion":true,"notificationsMailAnomaly":true},
    "alertConfigurationPush":{"notificationsPushOnOff":false,"notificationsPushIntrusion":false,
                              "notificationsPushAnomaly":true}}]
  ```
  Two channels (`Mail`, `Push`) and three categories: `Intrusion`, `Anomaly`, and `OnOff`
  (arm/disarm, **push only**). Contains personal data.
- **Update a user**: `PUT .../notifications/<userId>` with the full body -> `204`.
- **Relevance**: useful only for real-time push instead of polling, which needs a push
  receiving infrastructure. Polling `/state` is simpler for a first integration.

## 14. Logbook (async job)

- **Owner-only.** A restricted account's `POST` returns
  `403 {"message":"Access is denied"}`, so a client using such an account cannot read the
  history.
- **Create the job**: `POST /topaze/v5/systems/<systemId>/logbook` -> `202`
  `{"message":"ACCEPTED"}`. **The job id is in the `Location` response header**
  (`/v5/systems/<id>/logbook/<jobId>`, without the `/topaze` prefix), not in the body.
- **Poll**: `GET /topaze/v5/systems/<systemId>/logbook/<jobId>`
  - Running: `{"status":"request_status_pending","response":null,"error":null}`
  - Done: `{"status":"request_status_done","response":[]}`
- **Events** use i18n keys resolved app-side from Lokalise bundles:
  ```json
  {"date":"2026-09-07T15:22","title":"logEvent.36.label2",
   "details":[{"message":"logMessages.receivedCommand","args":[{"type":"Key","value":"logReceivedCommand.4"}]},
              {"message":"logMessages.groups","args":[{"type":"String","value":"1, 2"}]},
              {"message":"logMessages.distant"}]}
  ```
- Responses are large (256 kB seen) and full of personal data: keep out of Git.

### What the logbook records, and what it does not

- Commands appear as "system state change" with the received command, final state, groups,
  "remote", the device, and the **code used**: the master code for the owner, "service code
  2" for a restricted account. Actions from a client are therefore attributable and
  distinguishable.
- Mobile app session openings appear as "remote access through the transmission module".
- A `connect`→`get_state`→`disconnect` cycle from a client creates no logbook entry at all,
  even held for 20 minutes; only the mobile app creates one, presumably because it declares
  a user presence.
- **Consequence**: polling frequency is constrained only by session exclusivity against
  other devices, not by history readability.

---

## Recommended client strategy

1. **Opportunistic read**: try `get_state` directly. If it answers, another device holds a
   session and a client can read without opening one. On `500`, then and only then
   `connect` -> `get_state` -> `disconnect`.
2. **Commands**: `connect` -> command -> `disconnect`. Command responses already carry the
   full `systemState`, so it can feed straight into a client's own state cache.
3. **Delays**: poll fast (~1 Hz, like the app) while `tempo`/`tempogroup` runs, then return
   to a normal interval.
4. **`409` handling**: treat it as retryable, not as a failure — keep any last known state
   and retry rather than surfacing an error.

Five-minute polling is a reasonable default for a panel like this: a `connect` -> read ->
`disconnect` cycle of 2–3 seconds every 5 minutes occupies the panel about 1% of the time,
so another device would rarely see a `409`.

---

## Known gaps

- **Triggered state**: the `systemState` value and `openedIssueNumbers` contents during a
  real alarm are not documented here — impractical to provoke safely.
- **Schedule creation**: only `PUT`/`DELETE`/`activate` are documented; the `POST` shape for
  creating a new program is unknown.
- **Logbook event decoding**: the i18n keys are resolved app-side from a Lokalise bundle,
  not decoded here.
- **Idle session timeout**: the pure idle timeout with no polling at all is unknown.
- **Empty collections** (`cameras`, `videos`, `automatisms`, `scenarios`): return empty on
  an intrusion-only installation; their shape with the matching hardware or configuration is
  unknown.

## Caveats

- Not legal advice. Accessing your own data on your own hardware with your own account is
  not automatically compliant with the Daitem terms of service.
- A private API can change without notice. That fragility is structural.
- The mapping from Daitem hardware to Diagral equivalents is an unsourced inference and
  should not be relied on.
