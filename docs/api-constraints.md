# API constraints

Properties of the Daitem API that shape any integration, whether it uses the command line
or Python. The library works within them.

What the API looks like call by call is in the [API map](api/README.md), with requests and
answers in the [call reference](api-daitem.md).

## One session per panel

The panel accepts a single session at a time, across all accounts. While another device
holds it (typically the mobile app), opening one fails with `DaitemSessionBusyError`, or
exit code 3 on the command line. A second account does not get around it.

The library therefore holds a session only for the length of one command or one read, and
releases it at once. A program that polls should wait and try again when the panel is busy,
and keep reporting the last state it read.

## Reading the state needs a session

The state can only be read while a session exists, opened by any device. The façade's
`system.panel.read()` first reads without one, so it uses the mobile app's session when
there is one, and opens its own only otherwise.

## No live detector state

The inventory gives each device's identity, group, inhibition and faults (battery, tamper,
radio, masking, power). It does not give the open or closed state of a contact. An opening
only shows up in the event log, and only while the system is armed.

## Faults and firmware live in the inventory

Faults are only reported by the inventory, so a program must read it on every poll cycle
for fault reporting to stay current. It needs no panel session, so this is cheap. Every
device family has its own section: detectors, controls, sirens, transmitters, transceivers,
the box, and the fire and PPMS triggers.

The inventory also carries the firmware versions: a `SOFT` and a `RADIO` image for the
panel, and a `SOFT` one for its transmission module. No version exists per detector.

## Owner-only resources

The schedule and the event log answer only owner accounts. A restricted account gets
`DaitemForbiddenError`.

## Authentication

The Keycloak realm refuses the `password` grant. The library drives the browser flow
(`authorization_code` with PKCE) itself, without a browser, then renews the 30-minute access
token as needed. A stored refresh token lets later runs skip the login form.

The library posts the password only to Keycloak's own login action, on the sign-in server,
over https, and signs in on a cookie jar of its own: a single sign-on cookie left in a shared
HTTP session cannot sign it in as another account. Requests that carry a secret (the token
exchange, the logout, every write to the API) never follow a redirect.

## Retries

The library follows the app's rules, and sends less where they would add load:

- A rejected access token is renewed and the request sent once more, commands included,
  since nothing ran.
- A dropped connection on a read is retried twice, about 0.5 s apart. The delay varies a
  little, so clients that failed together do not come back together.
- A timeout is not retried, unlike in the app: a server that did not answer in time is not
  helped by the same request half a second later.
- A command or any other write is never replayed after a dropped connection or a timeout:
  the panel may have obeyed and only the answer been lost. The caller gets
  `DaitemConnectionError` and should read the state before sending it again.
- When the API says it is overloaded (`DaitemRateLimitedError`), or a gateway fails three
  times in a row, the client sends nothing for 5 s, then 10, 20 and so on up to 5 min, and
  raises `DaitemRateLimitedError` meanwhile. The panel release still goes out.

The app's rules, one by one: [protocol reference](api/reference.md#retries).

## Deferred connect

The app can receive a deferred answer to `connect`, and then polls for it. The library does
the same for up to 30 s, and releases the panel if the answer never comes.

## Client identification

The client identifies itself as what it is, rather than as the mobile app:

```
X-App-Name: eNova
X-App-Platform: python
X-App-Version: <library version>
User-Agent: pydaitem/<version> (+https://github.com/tomahoax/pydaitem) aiohttp/<v> Python/<v>
```

`X-App-Name` keeps the app's value because the gateway uses it to route to the right product
line. Without it the gateway answers 400, and with any other value 500.
