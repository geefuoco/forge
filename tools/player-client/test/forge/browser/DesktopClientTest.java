package forge.browser;

import com.google.gson.*;
import com.sun.net.httpserver.*;
import java.io.*;
import java.net.*;
import java.net.http.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

public final class DesktopClientTest {
    static final HttpClient HTTP = HttpClient.newHttpClient();
    static void check(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
    static HttpResponse<String> call(DesktopClient client, String method, String path, String cookie, String body, String origin) throws Exception {
        HttpRequest.Builder b = HttpRequest.newBuilder(URI.create(client.localOrigin() + path));
        if (cookie != null) b.header("Cookie", cookie);
        if (origin != null) b.header("Origin", origin);
        if (body == null) b.GET(); else b.header("Content-Type", "application/json").method(method, HttpRequest.BodyPublishers.ofString(body));
        return HTTP.send(b.build(), HttpResponse.BodyHandlers.ofString());
    }
    static String cookie(DesktopClient client) throws Exception {
        HttpResponse<String> response = call(client, "GET", "/api/v1/session", null, null, null);
        check(response.statusCode() == 200, "session bootstraps " + response.statusCode() + " " + response.body());
        String header = response.headers().firstValue("set-cookie").orElseThrow();
        check(header.contains("HttpOnly") && header.contains("SameSite=Strict"), "browser session cookie is protected");
        check(!response.body().contains(client.cookie), "session JSON has no credential");
        return header.split(";")[0];
    }
    static DesktopClient client(Path root, Path profile, String relay) throws Exception {
        DesktopClient client = new DesktopClient(new DesktopClient.Options(root, profile, relay, "test-release", true, false));
        client.server.start(); return client;
    }
    static void localBoundaryAndPersistence(Path root, Path profile) throws Exception {
        String decks = "{\"decks\":[{\"id\":\"draft\",\"name\":\"Draft\",\"entries\":[{\"name\":\"Uncatalogued card\",\"section\":\"main\",\"quantity\":1}]}]}";
        int firstPort;
        try (DesktopClient client = client(root, profile, "")) {
            firstPort = client.server.getAddress().getPort();
            check(call(client, "GET", "/", null, null, null).body().equals("test UI"), "local UI is served");
            check(call(client, "GET", "/api/v1/match", null, null, null).statusCode() == 401, "snapshots require cookie");
            check(call(client, "GET", "/api/v1/session", null, null, "https://evil.example").statusCode() == 403, "foreign origin cannot bootstrap");
            String cookie = cookie(client);
            check(call(client, "POST", "/api/v1/logout", cookie, "{}", null).statusCode() == 403, "POST requires local origin");
            check(call(client, "POST", "/api/v1/logout", cookie, "{}", "https://evil.example").statusCode() == 403, "foreign POST refused");
            check(call(client, "GET", "/api/v1/library", cookie, null, null).body().contains("\"exists\":false"), "new library is absent");
            check(call(client, "POST", "/api/v1/library", cookie, decks, client.localOrigin()).statusCode() == 200, "incomplete draft is persisted");
            check(call(client, "POST", "/api/v1/library", cookie, decks.replace("quantity\":1", "quantity\":1.5"), client.localOrigin()).statusCode() == 400, "fractional quantity refused");
            try (Socket socket = new Socket("127.0.0.1", firstPort)) {
                socket.getOutputStream().write("GET /api/v1/session HTTP/1.1\r\nHost: evil.example\r\nConnection: close\r\n\r\n".getBytes());
                check(new String(socket.getInputStream().readAllBytes()).startsWith("HTTP/1.1 403"), "DNS rebinding Host refused");
            }
        }
        try (DesktopClient client = client(root, profile, "")) {
            String cookie = cookie(client);
            String response = call(client, "GET", "/api/v1/library", cookie, null, null).body();
            check(response.contains("Uncatalogued card") && response.contains("\"exists\":true"), "library survives new app and local origin");
            check(call(client, "POST", "/api/v1/join", cookie, "{\"token\":\"old\"}", client.localOrigin()).statusCode() == 400, "partial invitations rejected");
        }
    }
    static void stubRelay(Path root, Path profile) throws Exception {
        HttpServer relay = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 8);
        String origin = "http://127.0.0.1:" + relay.getAddress().getPort();
        AtomicInteger acknowledgments = new AtomicInteger();
        AtomicInteger joinCalls = new AtomicInteger();
        AtomicReference<String> matchId = new AtomicReference<>();
        AtomicLong revision = new AtomicLong();
        List<Integer> statuses = new CopyOnWriteArrayList<>();
        relay.createContext("/", x -> {
            String path = x.getRequestURI().getPath();
            JsonObject request = x.getRequestMethod().equals("POST") ? Bridge.body(x) : new JsonObject();
            if (path.equals("/relay/v1/rooms")) Bridge.reply(x, 201, Bridge.map("schemaVersion", 1, "roomId", "abcdefghijklmnop", "hostToken", "host-secret", "inviteUrl", origin + "/#room=abcdefghijklmnop&invite=abcdefghijklmnop"));
            else if (path.endsWith("/join")) { joinCalls.incrementAndGet(); Bridge.reply(x, 200, Bridge.map("schemaVersion", 1, "guestToken", "guest-secret")); }
            else if (path.endsWith("/snapshot")) Bridge.reply(x, 200, Bridge.map("schemaVersion", 1, "seat", 1, "status", "starting", "revision", 0, "players", List.of(), "stack", List.of()));
            else if (path.endsWith("/host")) {
                check("Bearer host-secret".equals(x.getRequestHeaders().getFirst("Authorization")), "host token stays on native request");
                JsonObject snapshot = request.getAsJsonObject("snapshot");
                if (snapshot == null) { Bridge.reply(x, 200, Bridge.map("guestJoined", false, "commands", List.of())); x.close(); return; }
                check(snapshot.get("seat").getAsInt() == 1, "relay only receives seat one");
                matchId.set(snapshot.get("matchId").getAsString()); revision.set(snapshot.get("revision").getAsLong());
                JsonArray results = request.getAsJsonArray("results");
                if (!results.isEmpty()) {
                    statuses.add(results.get(0).getAsJsonObject().get("status").getAsInt());
                    if (acknowledgments.incrementAndGet() == 1) { x.close(); return; }
                }
                Bridge.reply(x, 200, Bridge.map("schemaVersion", 1, "guestJoined", false, "commands", List.of(Bridge.map("commandId", "one-command", "action", Bridge.map("kind", "concede", "matchId", matchId.get(), "revision", revision.get())))));
            } else Bridge.reply(x, 200, Bridge.map("schemaVersion", 1));
            x.close();
        });
        relay.start();
        try {
            try (DesktopClient host = client(root, profile.resolve("host"), origin)) {
                String cookie = cookie(host);
                HttpResponse<String> created = call(host, "POST", "/api/v1/matches", cookie, "{\"mode\":\"human\",\"humanDeck\":{},\"aiDeck\":{}}", host.localOrigin());
                check(created.statusCode() == 202, "host creates waiting match");
                check(!created.body().contains("host-secret"), "host credential absent from browser");
                long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(8);
                while (acknowledgments.get() < 3 && System.nanoTime() < deadline) Thread.sleep(50);
                check(acknowledgments.get() >= 3, "host resumes after lost acknowledgment");
                check(statuses.stream().allMatch(s -> s == 202), "replayed command gets original cached acceptance after lost ack");
                check(call(host, "POST", "/api/v1/matches", cookie, "{\"mode\":\"cpu\"}", host.localOrigin()).statusCode() == 409, "waiting match cannot be replaced");
                check(call(host, "POST", "/api/v1/logout", cookie, "{}", host.localOrigin()).statusCode() == 200, "logout preserves live app session");
                check(call(host, "GET", "/api/v1/match", cookie, null, null).body().contains(matchId.get()), "browser reconnect retains match");
            }
            try (DesktopClient guest = client(root, profile.resolve("guest"), origin)) {
                String cookie = cookie(guest);
                HttpResponse<String> joined = call(guest, "POST", "/api/v1/join", cookie, "{\"inviteUrl\":\"" + origin + "/#room=abcdefghijklmnop&invite=abcdefghijklmnop\"}", guest.localOrigin());
                check(joined.statusCode() == 200 && !joined.body().contains("guest-secret"), "guest joins without exposing native token");
                check(call(guest, "GET", "/api/v1/match", cookie, null, null).body().contains("\"seat\":1"), "guest reads remote seat");
                check(!Bridge.SeatView.initialized, "stub guest and waiting host never initialize Forge");
                check(joinCalls.get() == 1, "join called once");
            }
        } finally { relay.stop(0); }
    }
    public static void main(String[] args) throws Exception {
        Path root = Files.createTempDirectory("desktop-client-test-");
        Files.createDirectories(root.resolve("web/neoforge/dist"));
        Files.writeString(root.resolve("web/neoforge/dist/index.html"), "test UI");
        localBoundaryAndPersistence(root, root.resolve("profile"));
        stubRelay(root, root.resolve("stub"));
        boolean rejected = false;
        try { DesktopClient.origin("http://public.example", true); } catch (IllegalArgumentException e) { rejected = true; }
        check(rejected, "dev cannot use public HTTP relay");
        System.out.println("DesktopClientTest passed local HTTP boundaries, profile persistence, and stub relay lost-ack behavior; no real engine test");
    }
}
