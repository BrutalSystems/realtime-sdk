using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace BrutalSystems.Realtime.Client;

/// <summary>Scope value for every tenant. Pass a tenant id instead to reach one tenant.</summary>
public static class Announcements
{
    public const string Platform = "_platform";
}

public enum AnnouncementSeverity { Info, Warning, Critical }

/// <summary>Body of create/update. <paramref name="Scope"/> is required: <see cref="Announcements.Platform"/> or a tenant id.</summary>
public sealed record AnnouncementRequest(
    string Scope, AnnouncementSeverity Severity, string Title, string Body, DateTimeOffset EndsAt,
    DateTimeOffset? StartsAt = null, DateTimeOffset? EventAt = null, bool? Dismissible = null, string? RequestedBy = null);

public sealed record Announcement(
    string Id, int Revision, string Scope, AnnouncementSeverity Severity, string Title, string Body,
    DateTimeOffset StartsAt, DateTimeOffset EndsAt, DateTimeOffset? EventAt, bool Dismissible,
    DateTimeOffset CreatedAt, DateTimeOffset UpdatedAt, string CreatedBy, string? RequestedBy);

public sealed class AnnouncementsApiException(int status, string detail)
    : Exception($"announcements API {status}: {detail}")
{
    public int Status { get; } = status;
    public string Detail { get; } = detail;
}

/// <summary>Client for the realtime service's /announcements API (`_system` callers only):
/// a `_system` Bearer token provider, or the internal API key — exactly one.</summary>
public sealed class AnnouncementsClient
{
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        Converters = { new JsonStringEnumConverter(JsonNamingPolicy.SnakeCaseLower) },
    };

    private readonly HttpClient _http;
    private readonly string _root;
    private readonly Func<string>? _tokenProvider;
    private readonly string? _key;

    public AnnouncementsClient(HttpClient http, string baseUrl, Func<string>? tokenProvider = null,
        string? internalApiKey = null, string? apiPrefix = null)
    {
        if ((tokenProvider is null) == (internalApiKey is null))
            throw new ArgumentException("Pass exactly one of tokenProvider or internalApiKey.");
        _http = http;
        _tokenProvider = tokenProvider;
        _key = internalApiKey;
        var prefix = (apiPrefix ?? Environment.GetEnvironmentVariable("RT_API_PREFIX") ?? "/api/v1");
        if (!prefix.StartsWith('/')) throw new ArgumentException($"api prefix must start with '/': {prefix}");
        _root = $"{baseUrl.TrimEnd('/')}{prefix.TrimEnd('/')}/announcements";
    }

    public static Announcement Deserialize(string json) =>
        JsonSerializer.Deserialize<Announcement>(json, Json) ?? throw new JsonException("empty announcement");

    public async Task<Announcement> CreateAsync(AnnouncementRequest req, CancellationToken ct = default) =>
        Deserialize(await SendAsync(HttpMethod.Post, _root, req, ct));

    public async Task<Announcement> UpdateAsync(string id, AnnouncementRequest req, CancellationToken ct = default) =>
        Deserialize(await SendAsync(HttpMethod.Put, $"{_root}/{Uri.EscapeDataString(id)}", req, ct));

    public Task ClearAsync(string id, string scope, CancellationToken ct = default) =>
        SendAsync(HttpMethod.Delete, $"{_root}/{Uri.EscapeDataString(id)}?scope={Uri.EscapeDataString(scope)}", null, ct);

    public async Task<IReadOnlyList<Announcement>> ListAsync(string scope, CancellationToken ct = default) =>
        JsonSerializer.Deserialize<List<Announcement>>(
            await SendAsync(HttpMethod.Get, $"{_root}?scope={Uri.EscapeDataString(scope)}", null, ct), Json) ?? [];

    private async Task<string> SendAsync(HttpMethod method, string url, AnnouncementRequest? body, CancellationToken ct)
    {
        using var req = new HttpRequestMessage(method, url);
        if (body is not null) req.Content = JsonContent.Create(body, options: Json);
        if (_tokenProvider is not null) req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _tokenProvider());
        else req.Headers.Add("X-Internal-Api-Key", _key);
        using var resp = await _http.SendAsync(req, ct);
        var text = await resp.Content.ReadAsStringAsync(ct);
        if (!resp.IsSuccessStatusCode) throw new AnnouncementsApiException((int)resp.StatusCode, Detail(text));
        return text;
    }

    private static string Detail(string text)
    {
        try
        {
            using var doc = JsonDocument.Parse(text);
            return doc.RootElement.TryGetProperty("detail", out var d) ? d.ToString() : text;
        }
        catch (JsonException) { return text; }
    }
}
