namespace BrutalSystems.Realtime.Core;

public static class Auth
{
    /// <summary>The WebSocket subprotocol the server reads the JWT from: "Bearer.&lt;jwt&gt;".</summary>
    public static string BearerSubprotocol(string token) => $"Bearer.{token}";
}
