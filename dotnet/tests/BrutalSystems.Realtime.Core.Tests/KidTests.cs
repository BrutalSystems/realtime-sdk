using System.Security.Cryptography;
using Xunit;

namespace BrutalSystems.Realtime.Core.Tests;

public class KidTests
{
    [Fact]
    public void Compute_is_16_chars_and_url_safe()
    {
        using var rsa = TestKeys.NewRsa();
        var kid = Kid.Compute(rsa);
        Assert.Equal(16, kid.Length);
        Assert.DoesNotContain('+', kid);
        Assert.DoesNotContain('/', kid);
        Assert.DoesNotContain('=', kid);
    }

    [Fact]
    public void Compute_is_stable_for_a_key()
    {
        using var rsa = TestKeys.NewRsa();
        // Derives from the PUBLIC half, so re-importing only the public key yields the same kid.
        using var pub = RSA.Create();
        pub.ImportSubjectPublicKeyInfo(rsa.ExportSubjectPublicKeyInfo(), out _);
        Assert.Equal(Kid.Compute(rsa), Kid.Compute(pub));
    }
}
