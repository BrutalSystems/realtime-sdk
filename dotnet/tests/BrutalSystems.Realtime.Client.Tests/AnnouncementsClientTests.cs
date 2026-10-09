using System.Net;
using System.Text;
using System.Text.Json;
using Xunit;

namespace BrutalSystems.Realtime.Client.Tests;

public class AnnouncementsClientTests
{
    private const string AnnJson = """
        {"id":"01ABC","revision":1,"scope":"platform","severity":"warning","title":"T","body":"B",
         "starts_at":"2026-10-09T19:00:00Z","ends_at":"2026-10-09T19:30:00Z","event_at":null,"dismissible":true,
         "created_at":"2026-10-09T19:00:00Z","updated_at":"2026-10-09T19:00:00Z","created_by":"brokenhip-be",
         "requested_by":null}
        """;

    private sealed class Handler(HttpStatusCode status, string body) : HttpMessageHandler
    {
        public List<(HttpRequestMessage Req, string? Body)> Calls { get; } = [];
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage r, CancellationToken ct)
        {
            Calls.Add((r, r.Content is null ? null : await r.Content.ReadAsStringAsync(ct)));
            return new HttpResponseMessage(status) { Content = new StringContent(body, Encoding.UTF8, "application/json") };
        }
    }

    private static readonly DateTimeOffset Ends = new(2026, 10, 9, 19, 30, 0, TimeSpan.Zero);

    [Fact]
    public async Task Create_platform_posts_snake_case_body_with_bearer()
    {
        var h = new Handler(HttpStatusCode.Created, AnnJson);
        var c = new AnnouncementsClient(new HttpClient(h), "http://rt", tokenProvider: () => "tok", apiPrefix: "/api/v1");

        var a = await c.CreateAsync(new AnnouncementRequest(Announcements.Platform, AnnouncementSeverity.Warning, "T", "B", Ends));

        Assert.Equal("01ABC", a.Id);
        var (req, body) = h.Calls.Single();
        Assert.Equal(HttpMethod.Post, req.Method);
        Assert.Equal("http://rt/api/v1/announcements", req.RequestUri!.ToString());
        Assert.Equal("tok", req.Headers.Authorization!.Parameter);
        using var doc = JsonDocument.Parse(body!);
        var root = doc.RootElement;
        Assert.Equal("_platform", root.GetProperty("scope").GetString());
        Assert.Equal("warning", root.GetProperty("severity").GetString());
        Assert.True(root.TryGetProperty("ends_at", out _));
        Assert.False(root.TryGetProperty("starts_at", out _));      // nulls omitted
        Assert.False(root.TryGetProperty("dismissible", out _));
    }

    [Fact]
    public async Task Create_tenant_and_internal_key()
    {
        var h = new Handler(HttpStatusCode.Created, AnnJson);
        var c = new AnnouncementsClient(new HttpClient(h), "http://rt", internalApiKey: "k", apiPrefix: "/api/v1");

        await c.CreateAsync(new AnnouncementRequest("t1", AnnouncementSeverity.Critical, "T", "B", Ends, Dismissible: false, RequestedBy: "mike"));

        var (req, body) = h.Calls.Single();
        Assert.Equal("k", req.Headers.GetValues("X-Internal-Api-Key").Single());
        Assert.Null(req.Headers.Authorization);
        using var doc = JsonDocument.Parse(body!);
        Assert.Equal("t1", doc.RootElement.GetProperty("scope").GetString());
        Assert.False(doc.RootElement.GetProperty("dismissible").GetBoolean());
        Assert.Equal("mike", doc.RootElement.GetProperty("requested_by").GetString());
    }

    [Fact]
    public async Task List_and_clear_urls()
    {
        var h = new Handler(HttpStatusCode.OK, "[" + AnnJson + "]");
        var c = new AnnouncementsClient(new HttpClient(h), "http://rt", tokenProvider: () => "t", apiPrefix: "/api/v1");
        var list = await c.ListAsync("t1");
        Assert.Single(list);
        Assert.Equal("http://rt/api/v1/announcements?scope=t1", h.Calls[0].Req.RequestUri!.ToString());

        var h2 = new Handler(HttpStatusCode.OK, """{"id":"01ABC","scope":"tenant","status":"cleared"}""");
        var c2 = new AnnouncementsClient(new HttpClient(h2), "http://rt", tokenProvider: () => "t", apiPrefix: "/api/v1");
        await c2.ClearAsync("01ABC", Announcements.Platform);
        Assert.Equal(HttpMethod.Delete, h2.Calls[0].Req.Method);
        Assert.Equal("http://rt/api/v1/announcements/01ABC?scope=_platform", h2.Calls[0].Req.RequestUri!.ToString());
    }

    [Fact]
    public async Task Id_is_url_escaped()
    {
        var h = new Handler(HttpStatusCode.OK, AnnJson);
        var c = new AnnouncementsClient(new HttpClient(h), "http://rt", tokenProvider: () => "t", apiPrefix: "/api/v1");
        await c.UpdateAsync("a/b c", new AnnouncementRequest("t1", AnnouncementSeverity.Info, "T", "B", Ends));
        Assert.Equal("/api/v1/announcements/a%2Fb%20c", h.Calls[0].Req.RequestUri!.AbsolutePath);
    }

    [Fact]
    public async Task Error_carries_status_and_detail()
    {
        var h = new Handler(HttpStatusCode.Conflict, """{"detail":"Too many active announcements for this scope"}""");
        var c = new AnnouncementsClient(new HttpClient(h), "http://rt", tokenProvider: () => "t", apiPrefix: "/api/v1");
        var ex = await Assert.ThrowsAsync<AnnouncementsApiException>(() =>
            c.CreateAsync(new AnnouncementRequest("t1", AnnouncementSeverity.Info, "T", "B", Ends)));
        Assert.Equal(409, ex.Status);
        Assert.Contains("Too many", ex.Detail);
    }

    [Fact]
    public void Requires_exactly_one_auth()
    {
        Assert.Throws<ArgumentException>(() => new AnnouncementsClient(new HttpClient(), "http://rt"));
        Assert.Throws<ArgumentException>(() => new AnnouncementsClient(new HttpClient(), "http://rt", () => "t", "k"));
    }

    [Fact]
    public void Contract_upsert_payload_deserializes()
    {
        var json = File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "contract", "announcements.json"));
        using var doc = JsonDocument.Parse(json);
        var payload = doc.RootElement.GetProperty("events").GetProperty("upsert").GetProperty("data").GetProperty("payload");
        var withExtra = payload.GetRawText().TrimEnd('}') + ",\"future_field\":1}";
        var a = AnnouncementsClient.Deserialize(withExtra);
        Assert.Equal("01J9ZK3Q7M8N2P4R6S8T0V2W4X", a.Id);
        Assert.Equal(AnnouncementSeverity.Warning, a.Severity);
        Assert.Equal("platform", a.Scope);
    }
}
