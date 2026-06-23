using System.Text.Json;
using Xunit;

namespace BrutalSystems.Realtime.Core.Tests;

public class ChannelsTests
{
    [Fact]
    public void Classification_matches_contract_fixture()
    {
        var json = File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "contract", "channels.json"));
        using var doc = JsonDocument.Parse(json);
        foreach (var c in doc.RootElement.GetProperty("cases").EnumerateArray())
        {
            var name = c.GetProperty("name").GetString()!;
            var expected = c.GetProperty("type").GetString()!; // "public" | "private" | "presence"
            Assert.Equal(expected, Channels.Classify(name).ToString().ToLowerInvariant());
        }
    }

    [Fact]
    public void Presence_requires_dash_not_colon()
    {
        Assert.True(Channels.IsPresence("presence-room1"));
        Assert.False(Channels.IsPresence("presence:room1"));
        Assert.Equal(ChannelType.Public, Channels.Classify("presence:room1"));
    }

    [Fact]
    public void Matches_supports_wildcards()
    {
        Assert.True(Channels.Matches("worker.alpha.commands", "worker.*.commands"));
        Assert.False(Channels.Matches("notify.events", "worker.*"));
    }
}
