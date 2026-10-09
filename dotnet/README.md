# BrutalSystems.Realtime (.NET)

.NET SDK for the Brutal Systems realtime service. Two packages:

- **BrutalSystems.Realtime.Core** — wire contract: `TokenMinter`, `ClientTokenMinter`,
  `Kid`, `Jwks`, `Channels`, `Frames`.
- **BrutalSystems.Realtime.Client** — transport: `RealtimePublisher` (REST publish), `AnnouncementsClient` (tenant and platform announcements).

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

## Announcements

`AnnouncementsClient` manages banners through the service's `/announcements` API
(`_system` callers only). Both targets are first-class and there is no default
scope: `Announcements.Platform` reaches every tenant, a tenant id reaches one.

```csharp
var ann = new AnnouncementsClient(http, "https://realtime.example.com", tokenProvider: () => minter.Mint());
var ends = DateTimeOffset.UtcNow.AddMinutes(30);

await ann.CreateAsync(new AnnouncementRequest(Announcements.Platform, AnnouncementSeverity.Warning,
    "Maintenance", "DB down at 3:05 PM. Save your work.", ends));            // every tenant
await ann.CreateAsync(new AnnouncementRequest(tenantId, AnnouncementSeverity.Info, "Hello", "…", ends)); // one tenant

try { await ann.ListAsync(tenantId); }
catch (AnnouncementsApiException e) { Console.WriteLine($"{e.Status}: {e.Detail}"); }
```

`UpdateAsync` replaces the announcement - pass every field you want to keep; only
`starts_at` is preserved when omitted. `CreateAsync` is not idempotent - if a create
times out it may still have been stored; list before retrying.

The WebSocket subscriber is planned in a future release.
