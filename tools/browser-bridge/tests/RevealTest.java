package forge.browser;

import com.google.gson.*;
import forge.game.card.CardView;
import forge.game.player.PlayerView;
import forge.game.zone.ZoneType;
import forge.trackable.TrackableProperty;
import java.util.*;
import java.util.concurrent.*;

public class RevealTest {
    static int checks;
    static void check(boolean value, String message) {
        checks++;
        if (!value) throw new AssertionError(message);
    }
    static JsonObject waitPrompt(Bridge.MatchSession session) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
        do {
            JsonObject snapshot = JsonParser.parseString(session.snapshot).getAsJsonObject();
            if (snapshot.has("prompt")) return snapshot;
            Thread.sleep(5);
        } while (System.nanoTime() < deadline);
        throw new AssertionError("Reveal prompt did not appear");
    }
    static JsonObject action(Bridge.MatchSession session, JsonObject snapshot, String kind) {
        JsonObject action = new JsonObject();
        action.addProperty("matchId", session.id);
        action.add("revision", snapshot.get("revision"));
        action.add("promptId", snapshot.getAsJsonObject("prompt").get("id"));
        action.addProperty("kind", kind);
        return action;
    }
    public static void main(String[] args) throws Exception {
        Bridge.MatchSession session = new Bridge.MatchSession(new JsonObject());
        Bridge.PumpGui gui = new Bridge.PumpGui(session);
        session.human = new PlayerView(1, null);
        CardView hidden = new CardView(3, null, "Hidden library name");
        hidden.set(TrackableProperty.Zone, ZoneType.Library);
        hidden.set(TrackableProperty.Controller, new PlayerView(2, null));
        ExecutorService worker = Executors.newSingleThreadExecutor();
        try {
            Future<?> result = worker.submit(() -> gui.reveal("Revealed cards", List.of("<shown>", hidden)));
            JsonObject snapshot = waitPrompt(session), prompt = snapshot.getAsJsonObject("prompt");
            check(prompt.get("kind").getAsString().equals("reveal"), "Informational sentinel became choices");
            check(!prompt.has("min") && !prompt.has("max") && !prompt.has("choices"), "Reveal exposes selection bounds");
            check(prompt.getAsJsonArray("items").get(0).getAsString().equals("<shown>"), "Visible label changed");
            check(prompt.getAsJsonArray("items").get(1).getAsString().equals("Face-down card"), "Hidden card label lost");
            check(!session.snapshot.contains("Hidden library name"), "Reveal leaked hidden name");
            for (String kind : List.of("cancel", "choice", "card", "player", "number")) {
                check(session.submit(action(session, snapshot, kind)) != null, "Accepted non-acknowledgement " + kind);
                check(!result.isDone(), "Rejected answer completed reveal");
            }
            JsonObject stale = action(session, snapshot, "ok"); stale.addProperty("revision", 0);
            check(session.submit(stale) != null, "Accepted stale reveal revision");
            stale = action(session, snapshot, "ok"); stale.addProperty("promptId", "old");
            check(session.submit(stale) != null, "Accepted stale reveal prompt");
            check(!result.isDone(), "Reveal did not wait for acknowledgement");
            JsonObject acknowledgement = action(session, snapshot, "ok");
            check(session.submit(acknowledgement) == null, "Reveal acknowledgement rejected");
            result.get(5, TimeUnit.SECONDS);
            check(session.submit(acknowledgement) != null, "Accepted duplicate reveal acknowledgement");
            check(!JsonParser.parseString(session.snapshot).getAsJsonObject().has("prompt"), "Reveal remained pending");
            Future<List<String>> choice = worker.submit(() -> gui.getChoices("Choose", 1, 1, List.of("First", "Second"), null, null));
            snapshot = waitPrompt(session); prompt = snapshot.getAsJsonObject("prompt");
            check(prompt.get("kind").getAsString().equals("choices"), "Ordinary choice became reveal");
            check(session.submit(acknowledgement) != null, "Old acknowledgement advanced next choice");
            JsonObject answer = action(session, snapshot, "choice");
            JsonArray ids = new JsonArray(); ids.add(prompt.getAsJsonArray("choices").get(1).getAsJsonObject().get("id"));
            answer.add("choiceIds", ids);
            check(session.submit(answer) == null, "Ordinary choice rejected");
            check(choice.get(5, TimeUnit.SECONDS).equals(List.of("Second")), "Ordinary choice changed");
            Future<List<String>> direct = worker.submit(() -> gui.getChoices("Information", -1, -1, List.of("Card"), null, null));
            snapshot = waitPrompt(session);
            check(session.submit(action(session, snapshot, "ok")) == null, "Direct informational choice rejected");
            check(direct.get(5, TimeUnit.SECONDS).isEmpty(), "Reveal selected a card for the user");
            System.out.println("Passed " + checks + " reveal acknowledgement and ordinary-choice checks");
        } finally { worker.shutdownNow(); }
    }
}
