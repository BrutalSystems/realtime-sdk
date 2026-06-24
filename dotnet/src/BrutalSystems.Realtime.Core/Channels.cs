using System.Text.RegularExpressions;

namespace BrutalSystems.Realtime.Core;

public enum ChannelType { Public, Private, Presence }

public static class Channels
{
    /// <summary>Prefix rules mirror the server: private- -> Private, presence- -> Presence
    /// (dash, NOT colon), everything else -> Public.</summary>
    public static ChannelType Classify(string name) =>
        name.StartsWith("private-", StringComparison.Ordinal) ? ChannelType.Private
        : name.StartsWith("presence-", StringComparison.Ordinal) ? ChannelType.Presence
        : ChannelType.Public;

    public static bool IsPresence(string name) => Classify(name) == ChannelType.Presence;

    /// <summary>
    /// Returns <see langword="true"/> when <paramref name="channel"/> matches
    /// <paramref name="pattern"/> using a <c>*</c>-only glob.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Scope: only the <c>*</c> wildcard is supported — it matches any run of
    /// characters (including the empty string), equivalent to <c>.*</c> in a
    /// regular expression.
    /// </para>
    /// <para>
    /// <c>?</c> and <c>[...]</c> are treated as literal characters, not
    /// wildcards.  Matching is ordinal and case-sensitive.
    /// </para>
    /// <para>
    /// Full <c>fnmatch</c> parity (<c>?</c>, character classes) is intentionally
    /// deferred to the WebSocket-client release that will actually consume
    /// pattern matching; the current ACL patterns used by the server use
    /// <c>*</c> only.
    /// </para>
    /// </remarks>
    public static bool Matches(string channel, string pattern)
    {
        var rx = "^" + Regex.Escape(pattern).Replace("\\*", ".*") + "$";
        return Regex.IsMatch(channel, rx);
    }
}
