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

    /// <summary>fnmatch-style glob where '*' matches any run of characters.</summary>
    public static bool Matches(string channel, string pattern)
    {
        var rx = "^" + Regex.Escape(pattern).Replace("\\*", ".*") + "$";
        return Regex.IsMatch(channel, rx);
    }
}
