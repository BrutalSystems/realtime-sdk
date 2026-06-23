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

    public async Task PublishAsync(string channel, object data, CancellationToken ct = default)
    {
        var url = $"{_baseUrl}{_prefix}/channels/{Uri.EscapeDataString(channel)}/messages";
        using var req = new HttpRequestMessage(HttpMethod.Post, url)
        {
            Content = JsonContent.Create(new { data }, options: JsonOpts),
        };
        req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _tokenProvider());
        using var resp = await _http.SendAsync(req, ct);
        resp.EnsureSuccessStatusCode();
    }

    public Task PublishEventAsync(string channel, string @event, object payload, CancellationToken ct = default) =>
        PublishAsync(channel, new { @event, payload }, ct);
}
