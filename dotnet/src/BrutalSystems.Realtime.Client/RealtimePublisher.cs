using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;

namespace BrutalSystems.Realtime.Client;

/// <summary>Publishes messages to the realtime service over its REST API:
/// POST {baseUrl}{prefix}/channels/{channel}/messages  with body { "data": ... }.
/// The token provider is invoked per request (callers re-mint short-lived tokens).</summary>
public sealed class RealtimePublisher
{
    private static readonly JsonSerializerOptions JsonOpts = new(JsonSerializerDefaults.Web);

    private readonly HttpClient _http;
    private readonly Func<string> _tokenProvider;
    private readonly string _baseUrl;
    private readonly string _prefix;

    public RealtimePublisher(HttpClient http, Func<string> tokenProvider, string baseUrl, string? apiPrefix = null)
    {
        _http = http;
        _tokenProvider = tokenProvider;
        _baseUrl = baseUrl.TrimEnd('/');
        _prefix = ResolvePrefix(apiPrefix);
    }

    private static string ResolvePrefix(string? explicitPrefix)
    {
        var p = explicitPrefix
            ?? Environment.GetEnvironmentVariable("RT_API_PREFIX")
            ?? "/api/v1";
        if (!p.StartsWith('/')) throw new ArgumentException($"api prefix must start with '/': {p}");
        return p.TrimEnd('/');
    }

    public Task PublishAsync(string channel, object data, CancellationToken ct = default) =>
        PublishAsync(channel, data, scope: null, ct);

    /// <summary>Publishes into an explicit tenant <paramref name="scope"/>. Under the service's tenant_mode a
    /// system publisher (tenant_id "_system") serves every tenant, so it must name the target tenant here —
    /// otherwise the message lands in the "_system:" namespace no tenant subscriber listens on. A client
    /// token may only name its own tenant. Null = the caller's own tenant (the default behavior).</summary>
    public async Task PublishAsync(string channel, object data, string? scope, CancellationToken ct = default)
    {
        var url = $"{_baseUrl}{_prefix}/channels/{Uri.EscapeDataString(channel)}/messages";
        object body = scope is null ? new { data } : new { data, scope };
        using var req = new HttpRequestMessage(HttpMethod.Post, url)
        {
            Content = JsonContent.Create(body, options: JsonOpts),
        };
        req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _tokenProvider());
        using var resp = await _http.SendAsync(req, ct);
        resp.EnsureSuccessStatusCode();
    }

    public Task PublishEventAsync(string channel, string @event, object payload, CancellationToken ct = default) =>
        PublishAsync(channel, new { @event, payload }, scope: null, ct);

    /// <inheritdoc cref="PublishAsync(string, object, string?, CancellationToken)"/>
    public Task PublishEventAsync(string channel, string @event, object payload, string? scope, CancellationToken ct = default) =>
        PublishAsync(channel, new { @event, payload }, scope, ct);
}
