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
    static DesktopClient client(Path root, Path profile, String relay, String override) throws Exception {
        DesktopClient client = new DesktopClient(new DesktopClient.Options(root, profile, relay, "test-release", true, false, override));
        client.server.start(); return client;
    }
    static JsonObject settings(DesktopClient client, String cookie) throws Exception {
        HttpResponse<String> response = call(client, "GET", "/api/v1/settings", cookie, null, null);
        check(response.statusCode() == 200, "settings readable " + response.body());
        return JsonParser.parseString(response.body()).getAsJsonObject();
    }
    static void relaySettings(Path root, Path profile) throws Exception {
        String packaged = "https://packaged.example";
        String saved = "https://saved.example";
        try (DesktopClient client = client(root, profile, packaged)) {
            String cookie = cookie(client);
            check(call(client, "GET", "/api/v1/settings", null, null, null).statusCode() == 401, "settings require cookie");
            check(settings(client, cookie).get("source").getAsString().equals("packaged"), "packaged relay is initial default");
            check(call(client, "POST", "/api/v1/settings", cookie, "{\"relayOrigin\":\"https://evil.example\"}", "https://evil.example").statusCode() == 403, "foreign origin cannot save settings");
            for (String bad : List.of("http://public.example", "https://host.example/path", "https://name:pass@host.example", "https://host.example:0", "https://host.example:65536", "https://host.example?query", "https://host.example#part")) {
                check(call(client, "POST", "/api/v1/settings", cookie, JSON("relayOrigin", bad), client.localOrigin()).statusCode() == 400, "invalid relay rejected " + bad);
            }
            check(call(client, "POST", "/api/v1/settings", cookie, "{\"relayOrigin\":\"x\",\"reset\":true}", client.localOrigin()).statusCode() == 400, "ambiguous settings rejected");
            check(call(client, "POST", "/api/v1/settings", cookie, "{\"relayOrigin\":\"" + "x".repeat(8200) + "\"}", client.localOrigin()).statusCode() == 400, "oversized body rejected");
            check(settings(client, cookie).get("relayOrigin").getAsString().equals(packaged), "bad writes preserve relay");
            check(call(client, "POST", "/api/v1/settings", cookie, JSON("relayOrigin", saved), client.localOrigin()).statusCode() == 200, "relay saved");
            check(settings(client, cookie).get("source").getAsString().equals("saved"), "saved source shown");
            check(client.session().get("relayConfigured").equals(true), "session sees saved relay");
        }
        try (DesktopClient client = client(root, profile, packaged)) {
            String cookie = cookie(client);
            check(settings(client, cookie).get("relayOrigin").getAsString().equals(saved), "saved relay survives restart and new port");
            check(call(client, "POST", "/api/v1/settings", cookie, JSON("relayOrigin", ""), client.localOrigin()).statusCode() == 200, "empty relay saved");
            check(!client.session().get("relayConfigured").equals(true), "empty saved relay disables hosting");
        }
        try (DesktopClient client = client(root, profile, packaged)) {
            String cookie = cookie(client);
            check(settings(client, cookie).get("relayOrigin").getAsString().isEmpty(), "empty override survives restart");
            check(call(client, "POST", "/api/v1/settings", cookie, "{\"reset\":true}", client.localOrigin()).statusCode() == 200, "reset accepted");
            check(settings(client, cookie).get("relayOrigin").getAsString().equals(packaged), "reset restores packaged relay");
        }
        Files.writeString(profile.resolve("settings.json"), "{broken");
        try (DesktopClient client = client(root, profile, packaged)) {
            String cookie = cookie(client);
            JsonObject view = settings(client, cookie);
            check(view.get("source").getAsString().equals("invalidSaved") && view.get("relayOrigin").getAsString().isEmpty(), "corrupt saved relay fails closed");
            check(!view.get("warning").isJsonNull(), "corrupt settings warning visible");
            check(Files.readString(profile.resolve("settings.json")).equals("{broken"), "corrupt file preserved");
            check(call(client, "POST", "/api/v1/settings", cookie, JSON("relayOrigin", saved), client.localOrigin()).statusCode() == 200, "explicit save repairs corruption");
            check(settings(client, cookie).get("warning").isJsonNull(), "repair clears warning");
            JsonObject cpu = new JsonObject(); cpu.addProperty("mode", "cpu"); cpu.add("humanDeck", new JsonObject()); cpu.add("aiDeck", new JsonObject());
            check(call(client, "POST", "/api/v1/matches", cookie, cpu.toString(), client.localOrigin()).statusCode() == 202, "CPU match starts");
            check(settings(client, cookie).get("locked").getAsBoolean(), "CPU match locks settings");
            check(call(client, "POST", "/api/v1/settings", cookie, "{\"reset\":true}", client.localOrigin()).statusCode() == 409, "CPU match rejects settings change");
        }
        try (DesktopClient client = client(root, profile, packaged, "")) {
            String cookie = cookie(client);
            JsonObject view = settings(client, cookie);
            check(view.get("source").getAsString().equals("commandLine") && view.get("relayOrigin").getAsString().isEmpty(), "explicit CLI empty wins");
            check(!view.get("editable").getAsBoolean() && view.get("locked").getAsBoolean(), "CLI relay locked");
            check(call(client, "POST", "/api/v1/settings", cookie, JSON("relayOrigin", saved), client.localOrigin()).statusCode() == 409, "CLI relay cannot be changed");
        }
        Files.writeString(profile.resolve("settings.json"), "{\"schemaVersion\":1.5,\"relayOrigin\":\"" + saved + "\"}");
        try (DesktopClient client = client(root, profile, packaged, "https://cli.example")) {
            String cookie = cookie(client);
            JsonObject view = settings(client, cookie);
            check(view.get("relayOrigin").getAsString().equals("https://cli.example"), "CLI wins over corrupt saved settings");
            check(!view.get("warning").isJsonNull(), "CLI still shows corrupt profile warning");
        }
        Path failed = profile.resolve("failure");
        Files.createDirectories(failed.resolve("settings.json"));
        Files.writeString(failed.resolve("settings.json/blocker"), "keep");
        try (DesktopClient client = client(root, failed, packaged)) {
            String cookie = cookie(client);
            check(settings(client, cookie).get("source").getAsString().equals("invalidSaved"), "unreadable saved entry fails closed");
            check(call(client, "POST", "/api/v1/settings", cookie, JSON("relayOrigin", saved), client.localOrigin()).statusCode() == 503, "failed replacement reports unavailable");
            check(settings(client, cookie).get("source").getAsString().equals("invalidSaved"), "failed save preserves memory");
            check(call(client, "POST", "/api/v1/settings", cookie, "{\"reset\":true}", client.localOrigin()).statusCode() == 503, "failed deletion reports unavailable");
            check(settings(client, cookie).get("source").getAsString().equals("invalidSaved"), "failed reset preserves memory");
        }
    }
    static String JSON(String key, String value) { return DesktopClient.JSON.toJson(Bridge.map(key, value)); }
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
            try (DesktopClient host = client(root, profile.resolve("host"), "")) {
                String cookie = cookie(host);
                check(call(host, "POST", "/api/v1/settings", cookie, JSON("relayOrigin", origin), host.localOrigin()).statusCode() == 200, "host saves local relay before match");
                HttpResponse<String> created = call(host, "POST", "/api/v1/matches", cookie, "{\"mode\":\"human\",\"humanDeck\":{},\"aiDeck\":{}}", host.localOrigin());
                check(created.statusCode() == 202, "host creates waiting match");
                check(call(host, "POST", "/api/v1/settings", cookie, "{\"reset\":true}", host.localOrigin()).statusCode() == 409, "waiting host cannot change relay");
                check(!created.body().contains("host-secret"), "host credential absent from browser");
                long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(8);
                while (acknowledgments.get() < 3 && System.nanoTime() < deadline) Thread.sleep(50);
                check(acknowledgments.get() >= 3, "host resumes after lost acknowledgment");
                check(statuses.stream().allMatch(s -> s == 202), "replayed command gets original cached acceptance after lost ack");
                check(call(host, "POST", "/api/v1/matches", cookie, "{\"mode\":\"cpu\"}", host.localOrigin()).statusCode() == 409, "waiting match cannot be replaced");
                check(call(host, "POST", "/api/v1/logout", cookie, "{}", host.localOrigin()).statusCode() == 200, "logout preserves live app session");
                check(call(host, "GET", "/api/v1/match", cookie, null, null).body().contains(matchId.get()), "browser reconnect retains match");
            }
            try (DesktopClient guest = client(root, profile.resolve("guest"), "")) {
                String cookie = cookie(guest);
                HttpResponse<String> joined = call(guest, "POST", "/api/v1/join", cookie, "{\"inviteUrl\":\"" + origin + "/#room=abcdefghijklmnop&invite=abcdefghijklmnop\"}", guest.localOrigin());
                check(joined.statusCode() == 200 && !joined.body().contains("guest-secret"), "guest joins without exposing native token");
                check(call(guest, "POST", "/api/v1/settings", cookie, JSON("relayOrigin", origin), guest.localOrigin()).statusCode() == 409, "joined guest cannot change relay");
                check(call(guest, "GET", "/api/v1/match", cookie, null, null).body().contains("\"seat\":1"), "guest reads remote seat");
                check(!Bridge.SeatView.initialized, "stub guest and waiting host never initialize Forge");
                check(joinCalls.get() == 1, "join called once");
            }
            try (DesktopClient guest = client(root, profile.resolve("mismatch"), "")) {
                String cookie = cookie(guest);
                check(call(guest, "POST", "/api/v1/settings", cookie, JSON("relayOrigin", "https://different.example"), guest.localOrigin()).statusCode() == 200, "guest saves different relay");
                check(call(guest, "POST", "/api/v1/join", cookie, JSON("inviteUrl", origin + "/#room=abcdefghijklmnop&invite=abcdefghijklmnop"), guest.localOrigin()).statusCode() == 400, "different saved relay refuses invitation");
                check(joinCalls.get() == 1, "mismatched invitation makes no relay request");
            }
        } finally { relay.stop(0); }
    }
    public static void main(String[] args) throws Exception {
        Bridge.MatchSession pending = new Bridge.MatchSession(new JsonObject());
        JsonObject unversioned = new JsonObject();
        unversioned.addProperty("matchId", pending.id); unversioned.addProperty("kind", "concede");
        check(DesktopClient.submit(pending, unversioned).status() == 400, "installed actions require a revision including concession");
        Path root = Files.createTempDirectory("desktop-client-test-");
        Files.createDirectories(root.resolve("web/neoforge/dist"));
        Files.writeString(root.resolve("web/neoforge/dist/index.html"), "test UI");
        localBoundaryAndPersistence(root, root.resolve("profile"));
        relaySettings(root, root.resolve("settings-profile"));
        stubRelay(root, root.resolve("stub"));
        boolean rejected = false;
        try { DesktopClient.origin("http://public.example", true); } catch (IllegalArgumentException e) { rejected = true; }
        check(rejected, "dev cannot use public HTTP relay");
        System.out.println("DesktopClientTest passed local HTTP boundaries, profile persistence, and stub relay lost-ack behavior; no real engine test");
    }
}
