package forge.browser;

import com.google.gson.*;
import java.net.URI;
import java.net.http.*;
import java.util.List;
import java.util.concurrent.*;

public class RevisionTest {
    static int checks;
    static void check(boolean condition, String message) {
        checks++;
        if (!condition) throw new AssertionError(message);
    }
    static HttpResponse<String> post(HttpClient client, Bridge bridge, JsonObject action) throws Exception {
        return client.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:"
                + bridge.server.getAddress().getPort() + "/api/v1/action"))
                .header("Origin", bridge.origin).header("Authorization", "Bearer " + bridge.token)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(action.toString())).build(), HttpResponse.BodyHandlers.ofString());
    }
    static JsonObject action(Bridge.MatchSession session, JsonObject snapshot, String kind) {
        JsonObject action = new JsonObject();
        action.addProperty("matchId", session.id);
        action.addProperty("kind", kind);
        action.add("revision", snapshot.get("revision"));
        if (snapshot.has("prompt")) action.add("promptId", snapshot.getAsJsonObject("prompt").get("id"));
        return action;
    }
    public static void main(String[] args) throws Exception {
        Bridge bridge = new Bridge("https://revision-test.example", 0);
        Bridge.MatchSession session = new Bridge.MatchSession(new JsonObject());
        Bridge.PumpGui gui = new Bridge.PumpGui(session);
        bridge.match = session;
        bridge.server.start();
        ExecutorService game = Executors.newSingleThreadExecutor();
        try (HttpClient client = HttpClient.newHttpClient()) {
            Future<Boolean> pending = game.submit(() -> gui.showConfirmDialog("Confirm", "Revision", "Yes", "No", true));
            JsonObject snapshot = null;
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
            while (System.nanoTime() < deadline) {
                snapshot = JsonParser.parseString(session.snapshot).getAsJsonObject();
                if (snapshot.has("prompt")) break;
                Thread.sleep(5);
            }
            check(snapshot.has("prompt"), "Confirmation prompt did not appear");
            String unchanged = session.snapshot;
            for (String kind : List.of("ok", "concede")) {
                for (String value : List.of("null", "\"" + snapshot.get("revision") + "\"", "true", "[]", "{}",
                        snapshot.get("revision") + ".5", "9223372036854775808", "-9223372036854775809", "1e100")) {
                    JsonObject invalid = action(session, snapshot, kind);
                    invalid.add("revision", JsonParser.parseString(value));
                    HttpResponse<String> response = post(client, bridge, invalid);
                    check(response.statusCode() == 400 || response.statusCode() == 409,
                            "Expected client error for " + value + " revision on " + kind + ", got HTTP " + response.statusCode());
                    check(session.snapshot.equals(unchanged), "Rejected revision changed the visible decision");
                    check(!pending.isDone(), "Rejected revision answered the confirmation");
                    check(session.commands.isEmpty() && !session.inFlight, "Rejected revision queued an action");
                }
            }
            JsonObject missing = action(session, snapshot, "ok");
            missing.remove("revision");
            check(post(client, bridge, missing).statusCode() == 409, "Missing required revision was accepted");
            JsonObject stale = action(session, snapshot, "ok");
            stale.addProperty("revision", snapshot.get("revision").getAsLong() - 1);
            check(post(client, bridge, stale).statusCode() == 409, "Stale revision was accepted");
            check(session.snapshot.equals(unchanged) && !pending.isDone(), "Missing or stale revision changed the decision");
            JsonObject valid = action(session, snapshot, "ok");
            valid.add("revision", JsonParser.parseString(snapshot.get("revision") + ".0"));
            check(post(client, bridge, valid).statusCode() == 202, "Whole numeric revision was rejected");
            check(pending.get(5, TimeUnit.SECONDS), "Valid retry did not complete the confirmation");
            check(post(client, bridge, valid).statusCode() == 409, "Duplicate answer was accepted");

            Bridge.MatchSession conceding = new Bridge.MatchSession(new JsonObject());
            bridge.match = conceding;
            JsonObject concedeSnapshot = JsonParser.parseString(conceding.snapshot).getAsJsonObject();
            JsonObject concede = action(conceding, concedeSnapshot, "concede");
            concede.remove("revision");
            check(post(client, bridge, concede).statusCode() == 202, "Concession without optional revision was rejected");
            check(conceding.commands.size() == 1, "Concession was not queued once");
            System.out.println("Passed " + checks + " HTTP revision validation checks and valid retries");
        } finally {
            game.shutdownNow();
            bridge.server.stop(0);
            ((ExecutorService)bridge.server.getExecutor()).shutdownNow();
        }
    }
}
