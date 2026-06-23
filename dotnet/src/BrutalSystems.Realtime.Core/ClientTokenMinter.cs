using System.Security.Cryptography;

namespace BrutalSystems.Realtime.Core;

/// <summary>Mints browser-client tokens: the core 5 claims plus optional profile claims
/// (name, email, roles) the realtime service reads into its AuthenticatedUser. Lives
/// outside the 5-claim conformance fixture, which pins TokenMinter only.</summary>
public sealed class ClientTokenMinter
{
    private readonly RSA _key;
    private readonly string _issuer, _kid;
    private readonly int _ttlSeconds;
    private readonly string? _audience;

    public ClientTokenMinter(RSA privateKey, string issuer, int ttlSeconds = 300,
        string? audience = null, string? kid = null)
    {
        _key = privateKey;
        _issuer = issuer;
        _ttlSeconds = ttlSeconds;
        _audience = audience;
        _kid = kid ?? Kid.Compute(privateKey);
    }

    public string Mint(string subject, string tenantId, string? name = null,
        string? email = null, IEnumerable<string>? roles = null)
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var claims = new Dictionary<string, object?>
        {
            ["iss"] = _issuer,
            ["sub"] = subject,
            ["tenant_id"] = tenantId,
            ["iat"] = now,
            ["exp"] = now + _ttlSeconds,
        };
        if (_audience is not null) claims["aud"] = _audience;
        if (name is not null) claims["name"] = name;
        if (email is not null) claims["email"] = email;
        if (roles is not null) claims["roles"] = roles.ToArray();
        return Jwt.SignRs256(claims, _key, _kid);
    }
}
