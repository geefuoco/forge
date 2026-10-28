package forge.browser;

import com.google.gson.*;
import forge.game.card.CardView;
import forge.game.player.PlayerView;
import forge.game.zone.ZoneType;
import forge.trackable.*;
import forge.interfaces.IGameController;
import java.lang.reflect.Proxy;
import java.net.URI;
import java.net.http.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;

public class HostedTest {
    static int checks;
    static void check(boolean value, String message) {
        checks++;
        if (!value) throw new AssertionError(message);
    }
    static JsonObject snapshot(Bridge.SeatView seat) { return JsonParser.parseString(seat.snapshot).getAsJsonObject(); }
    static JsonObject action(Bridge.SeatView seat, String kind) {
        JsonObject out = new JsonObject();
        out.addProperty("matchId", seat.id); out.addProperty("revision", seat.revision); out.addProperty("kind", kind);
        if (seat.promptId != null) out.addProperty("promptId", seat.promptId);
        return out;
    }
    static HttpResponse<String> request(HttpClient client, Bridge bridge, String seat, String path, JsonObject body) throws Exception {
        var builder = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + bridge.server.getAddress().getPort() + "/api/v1/" + path))
                .header("Origin", bridge.origin).header("Authorization", "Bearer " + bridge.token).header("Content-Type", "application/json");
        if (seat != null) builder.header("X-Forge-Seat", seat);
        if (body != null) builder.POST(HttpRequest.BodyPublishers.ofString(body.toString()));
        return client.send(builder.build(), HttpResponse.BodyHandlers.ofString());
    }
    public static void main(String[] args) throws Exception {
        forge.util.Localizer.getInstance().initialize("en-US", "forge-gui/res/languages");
        JsonObject config = new JsonObject(); config.addProperty("mode", "human");
        Bridge.MatchSession match = new Bridge.MatchSession(config);
        Bridge.SeatView guest = match.seat(1);
        check(guest != null && guest.id.equals(match.id), "Human seats must share a match identity");
        check(match.seat(2) == null && new Bridge.MatchSession(new JsonObject()).seat(1) == null, "Invalid or CPU seat exists");
        CompletionTest.Fixture fixture = new CompletionTest.Fixture(new forge.game.player.PlayerOutcome[]{null, null});
        for (int i = 0; i < 2; i++) {
            Bridge.SeatView seat = match.seat(i);
            seat.gui = new Bridge.PumpGui(seat); seat.gui.setGameView(fixture.game().getView());
            seat.human = fixture.players().get(i).getView(); seat.status = "playing";
            CardView card = new CardView(100 + i, null, "Private card " + i);
            card.set(TrackableProperty.Zone, ZoneType.Hand); card.set(TrackableProperty.Controller, seat.human);
            seat.human.set(TrackableProperty.Hand, new TrackableCollection<>(card));
        }
        match.newPrompt("confirm", "Only host decision"); match.publish(); guest.publish();
        check(snapshot(match).has("prompt") && !snapshot(guest).has("prompt"), "Idle seat received another player's prompt");
        for (int i = 0; i < 2; i++) {
            Bridge.SeatView seat = match.seat(i);
            JsonArray players = snapshot(seat).getAsJsonArray("players");
            for (JsonElement entry : players) {
                JsonObject player = entry.getAsJsonObject();
                check(player.has("hand") == player.get("id").getAsString().equals(seat.pid(seat.human)), "Wrong player's private hand projected");
            }
            check(!seat.snapshot.contains("Private card " + (1 - i)), "Opponent card name leaked");
            check(!seat.cards.containsKey("" + (101 - i)), "Opponent hand card is actionable");
        }
        check(guest.submit(action(match, "ok")) != null, "Host prompt answered by guest");
        check(!match.inFlight, "Guest answer changed host input state");
        Bridge bridge = new Bridge("https://hosted-test.example", 0, true, "test-worker-token-which-is-long-enough");
        bridge.match = match; bridge.server.start();
        ExecutorService engine = Executors.newSingleThreadExecutor();
        try (HttpClient client = HttpClient.newHttpClient()) {
            check(request(client, bridge, null, "match", null).statusCode() == 403, "Missing internal seat accepted");
            check(request(client, bridge, "2", "match", null).statusCode() == 403, "Invalid internal seat accepted");
            check(request(client, bridge, "1", "match", null).body().equals(guest.snapshot), "Guest HTTP snapshot crossed seats");
            check(request(client, bridge, "1", "matches", config).statusCode() == 403, "Guest created match");
            CountDownLatch done = new CountDownLatch(1);
            AtomicReference<Thread> concessionThread = new AtomicReference<>();
            IGameController controller = (IGameController)Proxy.newProxyInstance(IGameController.class.getClassLoader(), new Class<?>[]{IGameController.class}, (proxy, method, values) -> {
                if (method.getName().equals("concede")) { concessionThread.set(Thread.currentThread()); done.countDown(); }
                return null;
            });
            guest.gui.setOriginalGameController(guest.human, controller);
            JsonObject concession = action(guest, "concede");
            check(request(client, bridge, "1", "action", concession).statusCode() == 202, "Off-turn concession rejected");
            check(concessionThread.get() == null, "HTTP thread called engine controller");
            check(request(client, bridge, "1", "action", concession).statusCode() == 409, "Duplicate concession accepted");
            Future<?> pumped = engine.submit(() -> match.pump(done)); pumped.get(5, TimeUnit.SECONDS);
            check(concessionThread.get() != null && concessionThread.get() != Thread.currentThread(), "Concession did not run on engine pump");
            check(match.terminal() && guest.terminal(), "Concession failed to finish both seat projections");
            check(!snapshot(match).has("prompt") && !snapshot(guest).has("prompt"), "Terminal seat retained decision");
            check(request(client, bridge, "0", "matches", config).statusCode() == 409, "Hosted terminal match replaced");
            bridge.match = new Bridge.MatchSession(new JsonObject());
            check(request(client, bridge, "1", "match", null).statusCode() == 403, "CPU seat read snapshot");
            check(request(client, bridge, "1", "action", concession).statusCode() == 403, "CPU seat sent action");
            System.out.println("Passed " + checks + " hosted seat, privacy, and off-turn concession checks");
        } finally { bridge.server.stop(0); engine.shutdownNow(); }
    }
}
