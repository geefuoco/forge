# Saved relay settings

The installed client can save a relay address after distribution. Players can use the same application archive when the operator supplies a relay address later. This feature does not deploy that relay.

## Ownership and precedence

Java owns the effective address and the profile file. The browser edits a draft and submits it to the local application. Established rooms retain their original relay address.

The address comes from the first applicable source in this order.

1. An explicit `--relay` launch option, including an empty value.
2. A saved profile value, including an empty value.
3. The packaged default.
4. No address.

The profile file is `settings.json`. Its format is `{"schemaVersion":1,"relayOrigin":"https://relay.example"}`. An empty address disables hosting. Removing the file restores the packaged default. The client preserves malformed files and displays a warning. Without a launch override, a malformed saved file disables hosting until the player saves or resets the address.

The client publishes a new configuration only after the profile write or deletion succeeds. Settings changes and game creation share the local request lock. Any owned match or room blocks changes until application exit, including a waiting lobby or a completed game. A launch override also blocks changes.

## Local API

Both methods use `/api/v1/settings` and require the application's authenticated local session. POST also requires the exact local Origin and JSON content type.

GET returns `schemaVersion`, `relayOrigin`, `source`, `editable`, `locked`, `warning`, and `packagedOrigin`. The source is `commandLine`, `saved`, `packaged`, `none`, or `invalidSaved`.

POST accepts exactly one of these bodies.

```json
{"relayOrigin":"https://relay.example"}
```

```json
{"reset":true}
```

An empty `relayOrigin` saves an explicit empty override. Reset removes the override. A successful response has the GET shape. A locked change returns HTTP 409. A persistence failure returns HTTP 503 and preserves the effective address.

Saved input is bounded to 8 KiB. Addresses are bounded to 2,048 characters and must be HTTPS origins. Credentials, queries, fragments, paths other than `/`, and ports outside 1 through 65,535 are rejected. Development mode permits HTTP on loopback. Save validates the address without contacting the relay.

## Design choice

| Candidate | Benefit | Decision |
| --- | --- | --- |
| Small immutable settings snapshot in DesktopClient | Reuses the existing request lock and keeps persistence beside its owner. | Selected. |
| Separate configuration object with saved and packaged state | Makes corruption and provenance explicit, but adds more stored state. | Retained its corrupt-file behavior. |

Two independent design proposals and a cross-judge chose the small snapshot. Corrupt saved settings disable hosting rather than silently selecting a different service. Local CPU play and the deck library remain available.
