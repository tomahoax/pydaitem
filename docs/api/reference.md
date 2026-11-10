# Protocol reference

What every call of Daitem Secure 6.0.3 has in common. Calls one by one:
[openapi.yaml](openapi.yaml). Panel states: [entities](entities.md#panel-states).
Context: [README](README.md).

## Authentication

Keycloak authorisation code flow with PKCE S256. The token answer gives an access token, a
refresh token and both lifetimes. Every Topaze call carries the access token.

| Setting | Value |
|---|---|
| Realm endpoints | `https://auth.atraltech.com/realms/daitem/protocol/openid-connect` |
| Client | `daitem-secure-app` |
| Redirect URI | `daitemsecure://auth` |
| Scope | `openid` |
| Topaze base URL | `https://appv3.tt-monitor.com/topaze` |

## Headers

| Header | Meaning |
|---|---|
| `Authorization` | `Bearer <access token>` from Keycloak, on every Topaze call. |
| `X-App-Name` | `eNova` for this app. The gateway rejects calls without it. |
| `X-App-Version` | The app version. Required by `connect`, free-form. |
| `X-App-Platform` | The platform. Optional. |
| `X-SessionId` | The panel session id (`ttmSessionId` from `connect`). Declared on every operation. |
| `X-Vendor` | Brand: `daitem` here. Declared on user info, logout, connect and push registration. |
| `X-Forwarded-For` | Client address. Declared on `connect` and on camera captures. |

The app adds an optional header only when it has a value (`connect`, for example,
adds `Authorization`, `X-Forwarded-For`, `X-SessionId` and `X-Vendor` that way).
Which operation declares which header: [openapi.yaml](openapi.yaml).

## Retries

The app's retry rules: 2 retries at most,
0.5 s apart.

| When | What the app does |
|---|---|
| HTTP 401 | Refresh the Keycloak token, then retry (2 retries at most). |
| HTTP 403 on keepAlive | The panel session is gone: start the session-lost flow, do not retry. |
| HTTP 403, 428, 500-599 | Decode the error body and translate its message. |
| Other failures | Retry after 0.5 s (2 retries at most), then give up. |

## Server error codes

The 29 codes the app knows. Errors come back as
`{"message": "<code>", "details": "<text>"}`.

| Code | Meaning |
|---|---|
| `transmitter.connection.sessionalreadyopen` | Another device holds the panel session (HTTP 409). |
| `status.nottmsessionid` | No panel session: connect first. |
| `transmitter.error.invalidsessionid` | Stale panel session: connect again. |
| `unexpected.error` | Generic; sometimes a session error in disguise. |
| `transmitter.connection.badpincode` | Wrong alarm code. Should trigger reauthentication. |
| `transmitter.connection.overlimit` | Too many attempts; back off. |
| `transmitter.connection.sessionrestricted` | This account may not open a session now. |
| `transmitter.connection.error` | Transmitter unreachable during connect. |
| `transmitter.connection.videolocked` | Video access locked. |
| `transmitter.error.accessforbidden` | The account lacks the right for this action. |
| `transmitter.error.ttdisconnected` | Transmitter offline: the panel cannot be reached at all. |
| `system.state.bad.module.version` | Module firmware too old for this request. |
| `zone.code.desynchronization` | Codes differ between panel and transmitter; installer needed. |
| `zone.code.wrong.size` | Code length refused. |
| `zone.code.restricted.already.exists` | Code already used by a restricted user. |
| `zone.code.owner.already.exists` | Code already used by the owner. |
| `error.user.code.installer` | The code given is the installer's. |
| `error.central.servicecode.duplicated` | Service code already in use. |
| `error.central.servicecode.forbidden` | Service code forbidden. |
| `installer.userCreation.error` | User creation failed. |
| `response.error.isalreadyowner` | Already the owner. |
| `response.error.isalreadyrestricted` | Already a restricted user. |
| `error.userUpdate.emailAlreadyExists` | E-mail already taken. |
| `error.scenario.noaction` | A scenario needs at least one action. |
| `error.owner.notmigrated` | Owner account not migrated to the new platform. |
| `error.user.notfound` | No installation tied to this account. |
| `error.connect.mydiagralusernotfound` | Sister brand account not found. |
| `sso.response.error` | Keycloak error. |
| `error.pool.full` | Server busy. Retry later. |

## Command statuses

`commandStatus` in the answer to an alarm command:

- `CMD_OK`
- `CMD TIMEOUT`
- `UNKNOWN CMD`
- `ERROR CMD FORBIDDEN`

## Third-party services

Listed so nothing is missed. None matter to a Topaze client, and the map leaves them out.

| Service | Hosts or role |
|---|---|
| Firebase (Analytics, Crashlytics, Installations) | app-analytics-services.com, firebase*.googleapis.com |
| Google Tag Manager and Analytics | googletagmanager.com, google-analytics.com |
| Sentry | ingest.de.sentry.io |
| Lokalise | translations delivered over the air |
| Dahua cloud SDK | live camera streams, peer to peer |
| Atral web pages | my.atraltech.com (terms, privacy, account deletion), atral-services.com |
