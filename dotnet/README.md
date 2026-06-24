# BrutalSystems.Realtime (.NET)

.NET SDK for the Brutal Systems realtime service. Two packages:

- **BrutalSystems.Realtime.Core** — wire contract: `TokenMinter`, `ClientTokenMinter`,
  `Kid`, `Jwks`, `Channels`, `Frames`.
- **BrutalSystems.Realtime.Client** — transport: `RealtimePublisher` (REST publish).

## Quickstart — mint a token and publish

```csharp
using System.Security.Cryptography;
using BrutalSystems.Realtime.Core;
using BrutalSystems.Realtime.Client;

using var rsa = RSA.Create();
rsa.ImportFromPem(File.ReadAllText("private.pem"));

var minter = new TokenMinter(rsa, issuer: "my-api", subject: "my-svc", tenantId: "_system",
                             audience: "my-audience");

using var http = new HttpClient();
var publisher = new RealtimePublisher(http, () => minter.Mint(), "https://realtime.example.com");
await publisher.PublishEventAsync("room1", "msg", new { text = "hi" });
```

Serve your JWKS so the service can verify your tokens:

```csharp
var jwks = Jwks.Export(rsa); // -> { keys: [ { kty, use, alg, kid, n, e } ] }
```

The WebSocket subscriber is planned in a future release.
