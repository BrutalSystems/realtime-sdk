using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Xunit;

namespace BrutalSystems.Realtime.Core.Tests;

public class TokenMinterTests
{
    // Decodes the payload segment of a JWT into a JsonElement (no signature check).
    private static JsonElement Payload(string jwt)
    {
        var seg = jwt.Split('.')[1];
        var pad = seg.Replace('-', '+').Replace('_', '/').PadRight((seg.Length + 3) / 4 * 4, '=');
        return JsonSerializer.Deserialize<JsonElement>(Convert.FromBase64String(pad));
    }

    private static IEnumerable<string> ClaimNames(string jwt) =>
        Payload(jwt).EnumerateObject().Select(p => p.Name);

    [Fact]
    public void Mint_emits_exactly_the_five_core_claims_when_no_audience()
    {
        using var rsa = TestKeys.NewRsa();
        var token = new TokenMinter(rsa, issuer: "example-api", subject: "example-service", tenantId: "_org", ttlSeconds: 300).Mint();

        Assert.Equal(
            new HashSet<string> { "iss", "sub", "tenant_id", "iat", "exp" },
            ClaimNames(token).ToHashSet());

        var p = Payload(token);
        Assert.Equal("example-api", p.GetProperty("iss").GetString());
        Assert.Equal("example-service", p.GetProperty("sub").GetString());
        Assert.Equal("_org", p.GetProperty("tenant_id").GetString());
        Assert.Equal(300, p.GetProperty("exp").GetInt64() - p.GetProperty("iat").GetInt64());
    }

    [Fact]
    public void Mint_adds_only_aud_when_audience_supplied()
    {
        using var rsa = TestKeys.NewRsa();
        var token = new TokenMinter(rsa, "brokenhip-be", "brokenhip-be", "_system", 3600, audience: "brokenhip-6eab9").Mint();

        Assert.Equal(
            new HashSet<string> { "iss", "sub", "tenant_id", "iat", "exp", "aud" },
            ClaimNames(token).ToHashSet());
        Assert.Equal("brokenhip-6eab9", Payload(token).GetProperty("aud").GetString());
    }

    [Fact]
    public void Header_has_rs256_and_default_kid_matches_Kid_Compute()
    {
        using var rsa = TestKeys.NewRsa();
        var token = new TokenMinter(rsa, "i", "s", "t").Mint();
        var headerSeg = token.Split('.')[0];
        var pad = headerSeg.Replace('-', '+').Replace('_', '/').PadRight((headerSeg.Length + 3) / 4 * 4, '=');
        var header = JsonSerializer.Deserialize<JsonElement>(Convert.FromBase64String(pad));
        Assert.Equal("RS256", header.GetProperty("alg").GetString());
        Assert.Equal(Kid.Compute(rsa), header.GetProperty("kid").GetString());
    }

    [Fact]
    public void Explicit_kid_overrides_the_derived_one()
    {
        using var rsa = TestKeys.NewRsa();
        var token = new TokenMinter(rsa, "i", "s", "t", kid: "brokenhip-be-2026").Mint();
        var headerSeg = token.Split('.')[0];
        var pad = headerSeg.Replace('-', '+').Replace('_', '/').PadRight((headerSeg.Length + 3) / 4 * 4, '=');
        var header = JsonSerializer.Deserialize<JsonElement>(Convert.FromBase64String(pad));
        Assert.Equal("brokenhip-be-2026", header.GetProperty("kid").GetString());
    }

    [Fact]
    public void Signature_verifies_against_the_public_key()
    {
        using var rsa = TestKeys.NewRsa();
        var token = new TokenMinter(rsa, "i", "s", "t").Mint();
        var parts = token.Split('.');
        var signingInput = Encoding.ASCII.GetBytes($"{parts[0]}.{parts[1]}");
        var sigSeg = parts[2].Replace('-', '+').Replace('_', '/').PadRight((parts[2].Length + 3) / 4 * 4, '=');
        var sig = Convert.FromBase64String(sigSeg);
        Assert.True(rsa.VerifyData(signingInput, sig, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1));
    }
}
