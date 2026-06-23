using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace BrutalSystems.Realtime.Core;

public sealed record EventFrame(string Channel, string Event, JsonObject Payload, string SenderId = "");

public sealed record InboundEvent(string Kind, string Channel, string SenderId, JsonObject Data);

public static class Frames
{
    private static readonly HashSet<string> InboundTypes = new()
    {
        "message", "presence:state", "presence:join", "presence:leave", "presence:update",
    };

    public static JsonObject Subscribe(string channel, string? scope = null, string? id = null)
    {
        var f = new JsonObject { ["type"] = "subscribe", ["channel"] = channel };
        if (scope is not null) f["scope"] = scope;
        if (id is not null) f["id"] = id;
        return f;
    }

    public static JsonObject Unsubscribe(string channel) =>
        new() { ["type"] = "unsubscribe", ["channel"] = channel };

    public static JsonObject Publish(string channel, object data, string? scope = null, string? id = null)
    {
        var f = new JsonObject
        {
            ["type"] = "publish",
            ["channel"] = channel,
            // Round-trip `data` through the Web serializer into a JsonNode so
            // anonymous objects land as a JSON object with their own key casing.
            ["data"] = JsonSerializer.SerializeToNode(data, WebOpts),
        };
        if (scope is not null) f["scope"] = scope;
        if (id is not null) f["id"] = id;
        return f;
    }

    public static JsonObject Ping() => new() { ["type"] = "ping" };

    public static EventFrame? ParseInbound(JsonObject msg)
    {
        if (msg["type"]?.GetValue<string>() != "message") return null;
        var channel = msg["channel"]?.GetValue<string>();
        if (string.IsNullOrEmpty(channel)) return null;
        var data = msg["data"] as JsonObject ?? new JsonObject();
        return new EventFrame(
            Channel: channel,
            Event: data["event"]?.GetValue<string>() ?? "",
            Payload: data["payload"] as JsonObject ?? new JsonObject(),
            SenderId: msg["sender_id"]?.GetValue<string>() ?? "");
    }

    public static InboundEvent? ParseFrame(JsonObject msg)
    {
        var kind = msg["type"]?.GetValue<string>();
        if (kind is null || !InboundTypes.Contains(kind)) return null;
        return new InboundEvent(
            Kind: kind,
            Channel: msg["channel"]?.GetValue<string>() ?? "",
            SenderId: msg["sender_id"]?.GetValue<string>() ?? "",
            Data: msg["data"] as JsonObject ?? new JsonObject());
    }

    private static readonly JsonSerializerOptions WebOpts = new(JsonSerializerDefaults.Web);
}
