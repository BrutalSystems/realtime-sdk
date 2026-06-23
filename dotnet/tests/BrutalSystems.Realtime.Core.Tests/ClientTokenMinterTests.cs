using System.Text.Json;
using Xunit;

namespace BrutalSystems.Realtime.Core.Tests;

public class ClientTokenMinterTests
{
    private static JsonElement Payload(string jwt)
    {
        var seg = jwt.Split('.')[1];
        var pad = seg.Replace('-', '+').Replace('_', '/').PadRight((seg.Length + 3) / 4 * 4, '=');
        return JsonSerializer.Deserialize<JsonElement>(Convert.FromBase64String(pad));
    }

    [Fact]
    public void Mint_includes_core_claims_plus_profile_and_aud()
    {
        using var rsa = TestKeys.NewRsa();
        var token = new ClientTokenMinter(rsa, "brokenhip-be", 3600, audience: "brokenhip-6eab9")
            .Mint(subject: "auth-user-1", tenantId: "tenant-abc", name: "Ada", email: "ada@x.com");

        var p = Payload(token);
        Assert.Equal("brokenhip-be", p.GetProperty("iss").GetString());
        Assert.Equal("auth-user-1", p.GetProperty("sub").GetString());
        Assert.Equal("tenant-abc", p.GetProperty("tenant_id").GetString());
        Assert.Equal("brokenhip-6eab9", p.GetProperty("aud").GetString());
        Assert.Equal("Ada", p.GetProperty("name").GetString());
        Assert.Equal("ada@x.com", p.GetProperty("email").GetString());
    }

    [Fact]
    public void Mint_omits_profile_claims_when_not_provided()
    {
        using var rsa = TestKeys.NewRsa();
        var token = new ClientTokenMinter(rsa, "brokenhip-be").Mint("u", "t");
        var names = Payload(token).EnumerateObject().Select(x => x.Name).ToHashSet();
        Assert.DoesNotContain("name", names);
        Assert.DoesNotContain("email", names);
        Assert.DoesNotContain("roles", names);
        Assert.DoesNotContain("aud", names);
    }

    [Fact]
    public void Mint_includes_roles_array_when_provided()
    {
        using var rsa = TestKeys.NewRsa();
        var token = new ClientTokenMinter(rsa, "brokenhip-be").Mint("u", "t", roles: new[] { "admin", "user" });
        var roles = Payload(token).GetProperty("roles").EnumerateArray().Select(e => e.GetString()).ToArray();
        Assert.Equal(new[] { "admin", "user" }, roles);
    }
}
