package forge.browser;

import com.google.gson.*;
import com.sun.net.httpserver.*;
import java.awt.Desktop;
import java.io.*;
import java.net.*;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;

public final class DesktopClient implements AutoCloseable {
    static final Gson JSON = new GsonBuilder().serializeNulls().create();
    record Response(int status, String body) { }
    record Room(String origin, String id, String credential, String invite, boolean guest) { }
    record Completed(String action, Response response) { }
    record Options(Path root, Path profile, String relay, String buildId, boolean dev, boolean open) {
        static Options parse(String[] args) throws Exception {
            Path root = Path.of(DesktopClient.class.getProtectionDomain().getCodeSource().getLocation().toURI()).toAbsolutePath();
            if (!Files.isDirectory(root)) root = root.getParent();
            Map<String,String> flags = new HashMap<>();
            boolean dev = false, open = true;
            for (int i = 0; i < args.length; i++) {
                if (args[i].equals("--dev")) dev = true;
                else if (args[i].equals("--no-open")) open = false;
                else if (Set.of("--root", "--profile", "--relay", "--build-id").contains(args[i]) && i + 1 < args.length)
                    flags.put(args[i], args[++i]);
                else throw new IllegalArgumentException("Unknown or incomplete option " + args[i]);
            }
            if (flags.containsKey("--root")) root = Path.of(flags.get("--root")).toAbsolutePath();
            JsonObject config = Files.isRegularFile(root.resolve("client-config.json"))
                    ? JsonParser.parseString(Files.readString(root.resolve("client-config.json"))).getAsJsonObject() : new JsonObject();
            String relay = flags.getOrDefault("--relay", config.has("relayOrigin") ? config.get("relayOrigin").getAsString() : "");
            String build = flags.getOrDefault("--build-id", config.has("buildId") ? config.get("buildId").getAsString() : "");
            if (build.isBlank() || build.length() > 128) throw new IllegalArgumentException("A release buildId is required in client-config.json or --build-id");
            if (!relay.isBlank()) relay = origin(relay, dev);
            Path profile = Path.of(flags.getOrDefault("--profile", Path.of(System.getProperty("user.home"), ".neoforge", "player-client").toString())).toAbsolutePath();
            return new Options(root, profile, relay, build, dev, open);
        }
    }
    final Options options;
    final HttpServer server;
    final ThreadPoolExecutor requests = new ThreadPoolExecutor(2, 8, 30, TimeUnit.SECONDS, new ArrayBlockingQueue<>(64));
    final ScheduledExecutorService exchange = Executors.newSingleThreadScheduledExecutor();
    final ExecutorService engine = Executors.newSingleThreadExecutor();
    final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).followRedirects(HttpClient.Redirect.NEVER).build();
    final String cookie = randomToken();
    final Path web;
    final LinkedHashMap<String,Completed> completed = new LinkedHashMap<>();
    volatile Bridge.MatchSession match;
    volatile Room room;
    volatile String relayError;
    volatile boolean closed;

    DesktopClient(Options options) throws Exception {
        this.options = options;
        web = options.root.resolve("web/neoforge/dist").toAbsolutePath().normalize();
        Files.createDirectories(options.profile);
        System.setProperty("user.home", options.profile.toString());
        System.setProperty("forge.player.profile", options.profile.toString());
        System.setProperty("forge.player.assets", options.root.resolve("forge-gui").toString() + File.separator);
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 32);
        server.setExecutor(requests);
        server.createContext("/", this::handle);
        exchange.scheduleWithFixedDelay(this::hostExchange, 0, 300, TimeUnit.MILLISECONDS);
    }
    static String randomToken() { byte[] b = new byte[32]; new SecureRandom().nextBytes(b); return Base64.getUrlEncoder().withoutPadding().encodeToString(b); }
    String localOrigin() { return "http://127.0.0.1:" + server.getAddress().getPort(); }
    Map<String,Object> session() { Room r = room; return Bridge.map("schemaVersion", 1, "authenticated", true, "canCreate", r == null || !r.guest, "seat", r != null && r.guest ? Integer.valueOf(1) : match == null ? null : Integer.valueOf(0), "hasMatch", match != null || r != null, "transport", "desktop", "relayConfigured", !options.relay.isBlank()); }
    boolean authenticated(HttpExchange x) {
        String header = x.getRequestHeaders().getFirst("Cookie");
        if (header == null) return false;
        for (String item : header.split(";")) if (MessageDigest.isEqual(item.trim().getBytes(StandardCharsets.UTF_8), ("neoforge=" + cookie).getBytes(StandardCharsets.UTF_8))) return true;
        return false;
    }
    void handle(HttpExchange x) throws IOException {
        try {
            x.getResponseHeaders().set("Cache-Control", "no-store");
            x.getResponseHeaders().set("X-Content-Type-Options", "nosniff");
            x.getResponseHeaders().set("Referrer-Policy", "no-referrer");
            String origin = x.getRequestHeaders().getFirst("Origin");
            if (!URI.create(localOrigin()).getAuthority().equals(x.getRequestHeaders().getFirst("Host")) || (origin != null && !origin.equals(localOrigin()))) { reply(x, 403, Bridge.error("Origin or Host rejected")); return; }
            String path = x.getRequestURI().getPath(), method = x.getRequestMethod();
            if (method.equals("POST") && !localOrigin().equals(origin)) { reply(x, 403, Bridge.error("Origin rejected")); return; }
            if (method.equals("GET") && path.equals("/api/v1/session")) {
                String fetch = x.getRequestHeaders().getFirst("Sec-Fetch-Site");
                if (fetch != null && !Set.of("same-origin", "none").contains(fetch)) { reply(x, 403, Bridge.error("Session bootstrap rejected")); return; }
                x.getResponseHeaders().add("Set-Cookie", "neoforge=" + cookie + "; Path=/api/v1/; HttpOnly; SameSite=Strict");
                reply(x, 200, session()); return;
            }
            if (!path.startsWith("/api/v1/")) { serveFile(x, path, method); return; }
            if (!authenticated(x)) { reply(x, 401, Bridge.error("Open this app's local page first")); return; }
            if (method.equals("GET") && path.equals("/api/v1/status")) { reply(x, 200, Bridge.map("schemaVersion", 1, "status", "ready")); return; }
            if (method.equals("GET") && path.equals("/api/v1/library")) {
                synchronized (this) { reply(x, 200, library()); } return;
            }
            if (method.equals("GET") && path.equals("/api/v1/match")) {
                Room r = room;
                if (r != null && r.guest) { send(x, relay(r, "GET", "/snapshot", null)); return; }
                if (r != null && relayError != null) { reply(x, 503, Bridge.error(relayError)); return; }
                Bridge.replyRaw(x, 200, hostSnapshot()); return;
            }
            if (!method.equals("POST")) { reply(x, 404, Bridge.error("Unknown endpoint")); return; }
            if (!"application/json".equalsIgnoreCase(x.getRequestHeaders().getFirst("Content-Type"))) { reply(x, 415, Bridge.error("Expected application/json")); return; }
            JsonObject body = Bridge.body(x);
            synchronized (this) {
                switch (path) {
                    case "/api/v1/session", "/api/v1/logout" -> reply(x, 200, session());
                    case "/api/v1/library" -> { saveLibrary(body); reply(x, 200, library()); }
                    case "/api/v1/matches" -> create(x, body);
                    case "/api/v1/invites" -> {
                        if (room == null || room.guest) reply(x, 409, Bridge.error("Host a friend match first"));
                        else reply(x, 200, Bridge.map("schemaVersion", 1, "inviteUrl", room.invite));
                    }
                    case "/api/v1/join" -> join(x, body);
                    case "/api/v1/action" -> {
                        Room r = room;
                        if (r != null && r.guest) send(x, relay(r, "POST", "/actions", Bridge.map("commandId", UUID.randomUUID().toString(), "action", body)));
                        else if (match == null || (r != null && !engineStarted)) reply(x, 409, Bridge.error("No running match"));
                        else send(x, submit(match.seat(0), body));
                    }
                    default -> reply(x, 404, Bridge.error("Unknown endpoint"));
                }
            }
        } catch (IllegalArgumentException | IllegalStateException e) { reply(x, 400, Bridge.error(e.getMessage() == null ? "Invalid request" : e.getMessage())); }
        catch (Exception e) { reply(x, 503, Bridge.error("Request could not complete; keep the app open and refresh")); }
        finally { x.close(); }
    }
    Map<String,Object> library() throws IOException {
        Path file = options.profile.resolve("library.json");
        if (!Files.exists(file)) return Bridge.map("schemaVersion", 1, "decks", List.of(), "exists", false);
        if (Files.size(file) > Bridge.LIMIT) throw new IOException("Library exceeds size limit");
        JsonObject value = JsonParser.parseString(Files.readString(file)).getAsJsonObject();
        validateLibrary(value);
        return Bridge.map("schemaVersion", 1, "decks", value.getAsJsonArray("decks"), "exists", true);
    }
    static void validateLibrary(JsonObject value) {
        if (!value.has("decks") || !value.get("decks").isJsonArray() || value.getAsJsonArray("decks").size() > 500) throw new IllegalArgumentException("Invalid deck library");
        Set<String> ids = new HashSet<>();
        for (JsonElement item : value.getAsJsonArray("decks")) {
            JsonObject deck = item.getAsJsonObject();
            String id = Bridge.string(deck, "id"), name = Bridge.string(deck, "name");
            if (id.length() > 128 || name.length() > 512 || !ids.add(id) || !deck.has("entries") || !deck.get("entries").isJsonArray() || deck.getAsJsonArray("entries").size() > 300) throw new IllegalArgumentException("Invalid saved deck");
            for (JsonElement entry : deck.getAsJsonArray("entries")) {
                JsonObject card = entry.getAsJsonObject();
                if (Bridge.string(card, "name").length() > 512 || !Set.of("main", "commander").contains(Bridge.string(card, "section"))) throw new IllegalArgumentException("Invalid saved card");
                JsonElement quantity = card.get("quantity");
                if (quantity == null || !quantity.isJsonPrimitive() || !quantity.getAsJsonPrimitive().isNumber()) throw new IllegalArgumentException("Invalid saved quantity");
                try {
                    long number = quantity.getAsBigDecimal().longValueExact();
                    if (number < 1 || number > 9_007_199_254_740_991L) throw new IllegalArgumentException("Invalid saved quantity");
                } catch (ArithmeticException e) { throw new IllegalArgumentException("Invalid saved quantity"); }
            }
        }
    }
    void saveLibrary(JsonObject body) throws IOException {
        validateLibrary(body);
        Path temporary = Files.createTempFile(options.profile, "library-", ".tmp");
        try {
            Files.writeString(temporary, JSON.toJson(Bridge.map("schemaVersion", 1, "decks", body.getAsJsonArray("decks"))));
            try { Files.move(temporary, options.profile.resolve("library.json"), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING); }
            catch (AtomicMoveNotSupportedException e) { Files.move(temporary, options.profile.resolve("library.json"), StandardCopyOption.REPLACE_EXISTING); }
        } finally { Files.deleteIfExists(temporary); }
    }
    void serveFile(HttpExchange x, String path, String method) throws IOException {
        if (!method.equals("GET")) { reply(x, 405, Bridge.error("Method rejected")); return; }
        Path file = web.resolve(path.equals("/") ? "index.html" : path.substring(1)).normalize();
        if (!file.startsWith(web) || !Files.isRegularFile(file) || !file.toRealPath().startsWith(web.toRealPath())) { reply(x, 404, Bridge.error("File not found")); return; }
        long size = Files.size(file);
        if (size > 32_000_000) { reply(x, 413, Bridge.error("File too large")); return; }
        String name = file.getFileName().toString();
        x.getResponseHeaders().set("Content-Type", name.endsWith(".html") ? "text/html; charset=utf-8" : name.endsWith(".js") ? "text/javascript; charset=utf-8" : name.endsWith(".css") ? "text/css; charset=utf-8" : "application/octet-stream");
        x.sendResponseHeaders(200, size); Files.copy(file, x.getResponseBody());
    }
    volatile boolean engineStarted;
    void create(HttpExchange x, JsonObject body) throws Exception {
        if (room != null || match != null) { reply(x, 409, Bridge.error("This app already owns a match")); return; }
        String mode = Bridge.string(body, "mode");
        if (!Set.of("cpu", "human").contains(mode)) throw new IllegalArgumentException("Unknown mode");
        if (!body.has("humanDeck") || !body.get("humanDeck").isJsonObject() || !body.has("aiDeck") || !body.get("aiDeck").isJsonObject()) throw new IllegalArgumentException("Two decks are required");
        Bridge.MatchSession candidate = new Bridge.MatchSession(body.deepCopy());
        if (mode.equals("human")) {
            if (options.relay.isBlank()) { reply(x, 409, Bridge.error("Online play needs a configured relay; CPU play works locally")); return; }
            Response response = request(options.relay + "/relay/v1/rooms", "POST", null, Bridge.map("protocolVersion", 1, "buildId", options.buildId));
            if (response.status != 201) { send(x, response); return; }
            JsonObject value = object(response);
            room = new Room(options.relay, Bridge.string(value, "roomId"), Bridge.string(value, "hostToken"), Bridge.string(value, "inviteUrl"), false);
        }
        match = candidate;
        if (room == null) startEngine();
        Bridge.replyRaw(x, 202, hostSnapshot());
    }
    void startEngine() { if (!engineStarted) { engineStarted = true; engine.execute(match::start); } }
    void join(HttpExchange x, JsonObject body) throws Exception {
        if (room != null || match != null) { reply(x, 409, Bridge.error("This app already owns a match")); return; }
        if (!body.has("inviteUrl")) throw new IllegalArgumentException("Paste the complete invitation in Join a friend");
        URI invite = URI.create(Bridge.string(body, "inviteUrl"));
        String remote = origin(new URI(invite.getScheme(), invite.getRawAuthority(), null, null, null).toString(), options.dev);
        if (invite.getUserInfo() != null || invite.getQuery() != null || !(invite.getPath().isEmpty() || invite.getPath().equals("/")) || invite.getRawFragment() == null) throw new IllegalArgumentException("Invalid invitation URL");
        if (!options.relay.isBlank() && !remote.equals(options.relay)) throw new IllegalArgumentException("Invitation uses a different relay");
        Map<String,String> fragment = new HashMap<>();
        for (String part : invite.getRawFragment().split("&")) {
            String[] pair = part.split("=", -1);
            if (pair.length != 2 || !Set.of("room", "invite").contains(pair[0]) || fragment.putIfAbsent(pair[0], pair[1]) != null || !pair[1].matches("[A-Za-z0-9_-]{16,128}")) throw new IllegalArgumentException("Invalid invitation URL");
        }
        if (fragment.size() != 2) throw new IllegalArgumentException("Invalid invitation URL");
        Response response = request(remote + "/relay/v1/rooms/" + fragment.get("room") + "/join", "POST", null, Bridge.map("protocolVersion", 1, "buildId", options.buildId, "inviteToken", fragment.get("invite")));
        if (response.status != 200) { send(x, response); return; }
        JsonObject value = object(response);
        room = new Room(remote, fragment.get("room"), Bridge.string(value, "guestToken"), null, true);
        reply(x, 200, session());
    }
    static String origin(String input, boolean dev) {
        URI uri = URI.create(input);
        boolean loopback = Set.of("localhost", "127.0.0.1", "::1", "[::1]").contains(uri.getHost() == null ? "" : uri.getHost());
        if (!("https".equals(uri.getScheme()) || (dev && loopback && "http".equals(uri.getScheme()))) || uri.getHost() == null || uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null || !(uri.getPath().isEmpty() || uri.getPath().equals("/"))) throw new IllegalArgumentException("Relay must be an HTTPS origin; --dev permits loopback HTTP");
        return uri.getScheme() + "://" + uri.getRawAuthority();
    }
    static JsonObject object(Response response) { return JsonParser.parseString(response.body).getAsJsonObject(); }
    Response relay(Room r, String method, String suffix, Object body) throws Exception { return request(r.origin + "/relay/v1/rooms/" + r.id + suffix, method, r.credential, body); }
    Response request(String url, String method, String credential, Object body) throws Exception {
        HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(12));
        if (credential != null) builder.header("Authorization", "Bearer " + credential);
        if (body == null) builder.GET();
        else builder.header("Content-Type", "application/json").method(method, HttpRequest.BodyPublishers.ofString(JSON.toJson(body)));
        HttpResponse<InputStream> response = http.send(builder.build(), HttpResponse.BodyHandlers.ofInputStream());
        try (InputStream stream = response.body()) {
            byte[] bytes = stream.readNBytes(Bridge.LIMIT + 1);
            if (bytes.length > Bridge.LIMIT) throw new IOException("Relay response too large");
            String json = new String(bytes, StandardCharsets.UTF_8);
            if (!JsonParser.parseString(json).isJsonObject()) throw new IOException("Invalid relay response");
            return new Response(response.statusCode(), json);
        }
    }
    static Response submit(Bridge.SeatView seat, JsonObject action) {
        try {
            if (!action.has("revision")) throw new IllegalArgumentException("Revision is required");
            String issue = seat.submit(action);
            return new Response(issue == null ? 202 : 409, JSON.toJson(issue == null ? Bridge.map("schemaVersion", 1, "accepted", true) : Bridge.error(issue)));
        } catch (IllegalArgumentException e) { return new Response(400, JSON.toJson(Bridge.error(e.getMessage()))); }
    }
    void hostExchange() {
        Room r = room;
        if (closed || r == null || r.guest) return;
        try {
            List<Object> results = new ArrayList<>();
            synchronized (completed) {
                completed.forEach((id, value) -> results.add(Bridge.map("commandId", id, "status", value.response.status, "body", JsonParser.parseString(value.response.body))));
            }
            Map<String,Object> payload = Bridge.map("results", results);
            Bridge.MatchSession current = match;
            if (current != null) payload.put("snapshot", JsonParser.parseString(current.seat(1).snapshot));
            Response response = relay(r, "POST", "/host", payload);
            if (response.status != 200) { relayError = "Relay unavailable; keep this host app open and refresh"; return; }
            JsonObject value = object(response);
            relayError = null;
            synchronized (this) { if (value.get("guestJoined").getAsBoolean() && match != null) startEngine(); }
            for (JsonElement entry : value.getAsJsonArray("commands")) {
                JsonObject command = entry.getAsJsonObject();
                String id = Bridge.string(command, "commandId");
                JsonObject action = command.getAsJsonObject("action");
                synchronized (completed) {
                    Completed prior = completed.get(id);
                    if (prior != null) {
                        if (!prior.action.equals(JSON.toJson(action))) throw new IOException("Relay reused a command identifier");
                        continue;
                    }
                    Response answer = match == null ? new Response(409, JSON.toJson(Bridge.error("No active match"))) : submit(match.seat(1), action);
                    completed.put(id, new Completed(JSON.toJson(action), answer));
                    while (completed.size() > 128) completed.remove(completed.keySet().iterator().next());
                }
            }
        } catch (Exception e) { relayError = "Relay connection failed; keep this host app open and refresh"; }
    }
    String hostSnapshot() {
        if (match == null) return waiting(false);
        if (room != null && !room.guest && !engineStarted)
            return JSON.toJson(Bridge.map("schemaVersion", 1, "status", "waiting", "matchId", match.id,
                    "revision", 0, "seat", 0, "players", List.of(), "stack", List.of()));
        return match.snapshot;
    }
    static String waiting(boolean guest) { return JSON.toJson(Bridge.map("schemaVersion", 1, "status", "idle", "revision", 0, "seat", guest ? 1 : 0, "players", List.of(), "stack", List.of())); }
    static void reply(HttpExchange x, int status, Object body) throws IOException { Bridge.replyRaw(x, status, JSON.toJson(body)); }
    static void send(HttpExchange x, Response response) throws IOException { Bridge.replyRaw(x, response.status, response.body); }
    @Override public void close() {
        closed = true;
        exchange.shutdownNow();
        Room r = room;
        if (r != null && !r.guest) try { relay(r, "POST", "/close", Map.of()); } catch (Exception ignored) { }
        server.stop(0); requests.shutdownNow(); engine.shutdownNow(); http.close();
    }
    public static void main(String[] args) throws Exception {
        DesktopClient client = new DesktopClient(Options.parse(args));
        Runtime.getRuntime().addShutdownHook(new Thread(client::close, "neoforge-shutdown"));
        client.server.start();
        System.out.println("NeoForge client listening at " + client.localOrigin());
        if (client.options.open && Desktop.isDesktopSupported()) try { Desktop.getDesktop().browse(URI.create(client.localOrigin())); } catch (Exception ignored) { }
    }
}
