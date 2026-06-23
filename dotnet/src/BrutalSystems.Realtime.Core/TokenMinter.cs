using System.Security.Cryptography;

namespace BrutalSystems.Realtime.Core;

/// <summary>Mints the minimal service-to-service token: iss, sub, tenant_id, iat, exp
/// (+ aud when configured). 1:1 with the Python realtime-core TokenMinter.</summary>
public sealed class TokenMinter
{
    private readonly RSA _key;
    private readonly string _issuer, _subject, _tenantId, _kid;
    private readonly int _ttlSeconds;
    private readonly string? _audience;

    public TokenMinter(RSA privateKey, string issuer, string subject, string tenantId,
        int ttlSeconds = 300, string? audience = null, string? kid = null)
    {
        _key = privateKey;
        _issuer = issuer;
        _subject = subject;
        _tenantId = tenantId;
        _ttlSeconds = ttlSeconds;
        _audience = audience;
        _kid = kid ?? Kid.Compute(privateKey);
    }

    public string Mint()
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var claims = new Dictionary<string, object?>
        {
            ["iss"] = _issuer,
            ["sub"] = _subject,
            ["tenant_id"] = _tenantId,
            ["iat"] = now,
            ["exp"] = now + _ttlSeconds,
        };
        if (_audience is not null) claims["aud"] = _audience;
        return Jwt.SignRs256(claims, _key, _kid);
    }
}
