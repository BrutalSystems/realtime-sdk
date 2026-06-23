using System.Security.Cryptography;
using System.Text.Json;
using Xunit;

namespace BrutalSystems.Realtime.Core.Tests;

public class JwksTests
{
    [Fact]
    public void Export_produces_one_rsa_sig_key_with_derived_kid()
    {
        using var rsa = TestKeys.NewRsa();
        var doc = Jwks.Export(rsa);
        var key = Assert.Single(doc.Keys);
        Assert.Equal("RSA", key.Kty);
        Assert.Equal("sig", key.Use);
        Assert.Equal("RS256", key.Alg);
        Assert.Equal(Kid.Compute(rsa), key.Kid);

        var p = rsa.ExportParameters(false);
        Assert.Equal(Jwt_B64Url(p.Modulus!), key.N);
        Assert.Equal(Jwt_B64Url(p.Exponent!), key.E);
    }

    [Fact]
    public void Export_honors_explicit_kid()
    {
        using var rsa = TestKeys.NewRsa();
        Assert.Equal("brokenhip-be-2026", Jwks.Export(rsa, "brokenhip-be-2026").Keys[0].Kid);
    }

    [Fact]
    public void Serializes_to_rfc7517_lowercase_shape()
    {
        using var rsa = TestKeys.NewRsa();
        var json = JsonSerializer.Serialize(Jwks.Export(rsa, "k1"), new JsonSerializerOptions(JsonSerializerDefaults.Web));
        using var doc = JsonDocument.Parse(json);
        var key0 = doc.RootElement.GetProperty("keys")[0];
        foreach (var f in new[] { "kty", "use", "alg", "kid", "n", "e" })
            Assert.True(key0.TryGetProperty(f, out _), $"missing {f}");
    }

    [Fact]
    public void BearerSubprotocol_format()
    {
        Assert.Equal("Bearer.abc.def", Auth.BearerSubprotocol("abc.def"));
    }

    private static string Jwt_B64Url(byte[] b) =>
        Convert.ToBase64String(b).TrimEnd('=').Replace('+', '-').Replace('/', '_');
}
