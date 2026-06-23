using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using Xunit;

namespace BrutalSystems.Realtime.Core.Tests;

public class FramesTests
{
    private static JsonObject Fixture(string section, string key)
    {
        var json = File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "contract", "frames.json"));
        return JsonNode.Parse(json)![section]![key]!.AsObject();
    }

    [Fact]
    public void Client_builders_match_fixture()
    {
        Assert.True(JsonNode.DeepEquals(Frames.Subscribe("room1"), Fixture("client", "subscribe")));
        Assert.True(JsonNode.DeepEquals(Frames.Unsubscribe("room1"), Fixture("client", "unsubscribe")));
        Assert.True(JsonNode.DeepEquals(
            Frames.Publish("room1", new { @event = "msg", payload = new { text = "hi" } }),
            Fixture("client", "publish")));
        Assert.True(JsonNode.DeepEquals(Frames.Ping(), Fixture("client", "ping")));
    }

    [Fact]
    public void Publish_includes_scope_when_given()
    {
        var expected = new JsonObject
        {
            ["type"] = "publish",
            ["channel"] = "room1",
            ["data"] = new JsonObject { ["x"] = 1 },
            ["scope"] = "_platform",
        };
        Assert.True(JsonNode.DeepEquals(Frames.Publish("room1", new { x = 1 }, scope: "_platform"), expected));
    }

    [Fact]
    public void ParseInbound_reads_message_frame()
    {
        var evt = Frames.ParseInbound(Fixture("server", "message"));
        Assert.NotNull(evt);
        Assert.Equal("room1", evt!.Channel);
        Assert.Equal("msg", evt.Event);
        Assert.Equal("u1", evt.SenderId);
        Assert.Equal("hi", evt.Payload["text"]!.GetValue<string>());
    }

    [Fact]
    public void ParseInbound_ignores_control_frames()
    {
        Assert.Null(Frames.ParseInbound(Fixture("server", "subscription_succeeded")));
        Assert.Null(Frames.ParseInbound(Fixture("server", "pong")));
    }

    [Theory]
    [InlineData("presence:state")]
    [InlineData("presence:join")]
    [InlineData("presence:leave")]
    [InlineData("presence:update")]
    public void ParseFrame_surfaces_message_and_presence(string kind)
    {
        var evt = Frames.ParseFrame(Fixture("server", kind));
        Assert.NotNull(evt);
        Assert.Equal(kind, evt!.Kind);
        Assert.Equal("presence-room1", evt.Channel);
    }

    [Fact]
    public void ParseFrame_ignores_control_frames()
    {
        foreach (var k in new[] { "pong", "subscription_succeeded", "subscription_error", "unsubscribed", "error" })
            Assert.Null(Frames.ParseFrame(Fixture("server", k)));
    }
}
