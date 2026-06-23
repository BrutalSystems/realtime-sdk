using System.Net;
using System.Text.Json;
using Xunit;

namespace BrutalSystems.Realtime.Client.Tests;

public class RealtimePublisherTests
{
    private sealed class CapturingHandler : HttpMessageHandler
    {
        public HttpRequestMessage? Request;
        public string? Body;
        public HttpStatusCode Status = HttpStatusCode.OK;

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            Request = request;
            Body = request.Content is null ? null : await request.Content.ReadAsStringAsync(ct);
            return new HttpResponseMessage(Status);
        }
    }

    [Fact]
    public async Task PublishAsync_posts_to_default_prefix_with_bearer_and_data_envelope()
    {
        var handler = new CapturingHandler();
        using var http = new HttpClient(handler);
        var pub = new RealtimePublisher(http, () => "tok-123", "http://realtime:8101");

        await pub.PublishAsync("dm.t1.a.b", new { @event = "message_created", payload = new { id = "m1" } });

        Assert.Equal(HttpMethod.Post, handler.Request!.Method);
        Assert.Equal("http://realtime:8101/api/v1/channels/dm.t1.a.b/messages", handler.Request.RequestUri!.ToString());
        Assert.Equal("Bearer", handler.Request.Headers.Authorization!.Scheme);
        Assert.Equal("tok-123", handler.Request.Headers.Authorization.Parameter);

        using var doc = JsonDocument.Parse(handler.Body!);
        var data = doc.RootElement.GetProperty("data");
        Assert.Equal("message_created", data.GetProperty("event").GetString());
        Assert.Equal("m1", data.GetProperty("payload").GetProperty("id").GetString());
    }

    [Fact]
    public async Task PublishAsync_uses_explicit_prefix_and_url_encodes_channel()
    {
        var handler = new CapturingHandler();
        using var http = new HttpClient(handler);
        var pub = new RealtimePublisher(http, () => "t", "http://realtime:8101/", apiPrefix: "/rt/");

        await pub.PublishAsync("dm.inbox.t1.user one", new { x = 1 });

        Assert.Equal("http://realtime:8101/rt/channels/dm.inbox.t1.user%20one/messages",
            handler.Request!.RequestUri!.ToString());
    }

    [Fact]
    public async Task PublishEventAsync_wraps_event_and_payload()
    {
        var handler = new CapturingHandler();
        using var http = new HttpClient(handler);
        var pub = new RealtimePublisher(http, () => "t", "http://realtime:8101");

        await pub.PublishEventAsync("room1", "read_advanced", new { conversation_id = "c1" });

        using var doc = JsonDocument.Parse(handler.Body!);
        var data = doc.RootElement.GetProperty("data");
        Assert.Equal("read_advanced", data.GetProperty("event").GetString());
        Assert.Equal("c1", data.GetProperty("payload").GetProperty("conversation_id").GetString());
    }

    [Fact]
    public async Task PublishAsync_throws_on_non_success()
    {
        var handler = new CapturingHandler { Status = HttpStatusCode.InternalServerError };
        using var http = new HttpClient(handler);
        var pub = new RealtimePublisher(http, () => "t", "http://realtime:8101");
        await Assert.ThrowsAsync<HttpRequestException>(() => pub.PublishAsync("room1", new { x = 1 }));
    }
}
