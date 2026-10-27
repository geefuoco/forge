package forge.browser;

import com.google.gson.*;
import forge.card.CardType;
import forge.card.MagicColor;
import forge.game.card.CardView;
import forge.game.keyword.Keyword;
import forge.game.keyword.KeywordCollectionView;
import forge.game.keyword.KeywordView;
import forge.game.player.PlayerView;
import forge.game.zone.ZoneType;
import forge.trackable.TrackableProperty;
import java.util.*;
import java.util.concurrent.*;

public class AllocationTest {
    static int checks;
    record ViewKeyword(Keyword keyword) implements KeywordView {
        @Override public String original() { return keyword.name(); }
        @Override public String title() { return keyword.name(); }
        @Override public String reminderText() { return ""; }
    }
    static CardView card(int id, String name, int lethal, String... keywords) {
        CardView card = new CardView(id, null, name);
        card.set(TrackableProperty.LethalDamage, lethal);
        card.getCurrentState().set(TrackableProperty.Type, new CardType(List.of("Creature"), true));
        card.getCurrentState().set(TrackableProperty.Keywords, new KeywordCollectionView(
                Arrays.stream(keywords).map(k -> (KeywordView)new ViewKeyword(Keyword.valueOf(k.toUpperCase(Locale.ROOT)))).toList()));
        return card;
    }
    static void check(boolean value, String message) {
        checks++;
        if (!value) throw new AssertionError(message);
    }
    static final class Decision implements AutoCloseable {
        final Bridge.MatchSession session = new Bridge.MatchSession(new JsonObject());
        final Bridge.PumpGui gui = new Bridge.PumpGui(session);
        final ExecutorService worker = Executors.newSingleThreadExecutor();
        Future<?> result;
        JsonObject snapshot, prompt;
        Decision() { session.human = new PlayerView(1, null); }
        void start(Callable<?> task) throws Exception {
            result = worker.submit(task);
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
            do {
                snapshot = JsonParser.parseString(session.snapshot).getAsJsonObject();
                if (snapshot.has("prompt")) {
                    prompt = snapshot.getAsJsonObject("prompt");
                    check(prompt.get("kind").getAsString().equals("allocation"), "Expected an allocation prompt");
                    return;
                }
                if (result.isDone()) result.get();
                Thread.sleep(5);
            } while (System.nanoTime() < deadline);
            throw new AssertionError("Allocation prompt did not appear");
        }
        JsonObject action(int... amounts) {
            JsonObject action = new JsonObject();
            action.addProperty("matchId", session.id);
            action.add("revision", snapshot.get("revision"));
            action.add("promptId", prompt.get("id"));
            action.addProperty("kind", "allocation");
            JsonArray allocations = new JsonArray();
            JsonArray targets = prompt.getAsJsonArray("targets");
            for (int i = 0; i < amounts.length; i++) {
                JsonObject entry = new JsonObject();
                entry.add("id", targets.get(i).getAsJsonObject().get("id"));
                entry.addProperty("amount", amounts[i]);
                allocations.add(entry);
            }
            action.add("allocations", allocations);
            return action;
        }
        void rejects(JsonObject action, String description) {
            check(session.submit(action) != null, "Accepted " + description);
            check(!result.isDone(), "Rejected action completed the decision");
        }
        Map<?,?> accepts(JsonObject action) throws Exception {
            check(session.submit(action) == null, "Rejected legal assignment");
            return (Map<?,?>)result.get(5, TimeUnit.SECONDS);
        }
        @Override public void close() {
            worker.shutdownNow();
        }
    }
    public static void main(String[] args) throws Exception {
        CardView source = card(10, "Trampling attacker", 4, "Trample");
        CardView first = card(11, "First blocker", 2), second = card(12, "Second blocker", 3);
        PlayerView defender = new PlayerView(2, null);
        defender.set(TrackableProperty.Name, "Defender");
        try (Decision d = new Decision()) {
            d.start(() -> d.gui.assignCombatDamage(source, List.of(first, second), 7, defender, false, false));
            d.rejects(d.action(1, 4, 2), "damage past an earlier surviving blocker");
            d.rejects(d.action(2, 2, 3), "trample before lethal on every blocker");
            d.rejects(d.action(2, 3, 3), "too much damage");
            d.rejects(d.action(-1, 3, 5), "negative damage");
            JsonObject skip = d.action(); skip.addProperty("kind", "skip");
            d.rejects(skip, "skip without permission");
            JsonObject wrongKind = d.action(); wrongKind.addProperty("kind", "ok");
            d.rejects(wrongKind, "ordinary OK during allocation");
            JsonObject stale = d.action(2, 3, 2); stale.addProperty("revision", 0);
            d.rejects(stale, "stale revision");
            stale = d.action(2, 3, 2); stale.addProperty("promptId", "old-prompt");
            d.rejects(stale, "stale prompt");
            Map<?,?> result = d.accepts(d.action(2, 3, 2));
            check(result.get(first).equals(2) && result.get(second).equals(3) && result.get(null).equals(2), "Combat map did not preserve blocker identity and defender sentinel");
        }
        try (Decision d = new Decision()) {
            d.start(() -> d.gui.assignCombatDamage(source, List.of(first, second), 3, defender, true, true));
            d.rejects(d.action(0, 2, 1), "modern-order trample past a surviving blocker");
            Map<?,?> result = d.accepts(d.action(0, 3, 0));
            check(result.get(first).equals(0) && result.get(second).equals(3) && result.get(null).equals(0), "Modern split or zero entries were lost");
        }
        try (Decision d = new Decision()) {
            source.getCurrentState().set(TrackableProperty.HasDivideDamage, true);
            d.start(() -> d.gui.assignCombatDamage(source, List.of(first, second), 3, defender, true, true));
            Map<?,?> result = d.accepts(d.action(0, 0, 3));
            check(result.get(null).equals(3), "Divide-as-you-choose did not reach defender");
            source.getCurrentState().set(TrackableProperty.HasDivideDamage, false);
        }
        try (Decision d = new Decision()) {
            d.start(() -> d.gui.assignCombatDamage(source, List.of(first, second), 3, defender, false, true));
            JsonObject skip = d.action(); skip.addProperty("kind", "skip");
            check(d.session.submit(skip) == null && d.result.get(5, TimeUnit.SECONDS) == null, "Allowed skip did not defer the attacker");
        }
        try (Decision d = new Decision()) {
            CardView deathtouch = card(13, "Deathtouch attacker", 4, "Trample", "Deathtouch");
            CardView walker = card(14, "Planeswalker blocker", 99);
            walker.getCurrentState().set(TrackableProperty.Type, new CardType(List.of("Planeswalker"), true));
            walker.getCurrentState().set(TrackableProperty.Loyalty, "3");
            d.start(() -> d.gui.assignCombatDamage(deathtouch, List.of(first, walker), 5, defender, false, false));
            JsonArray targets = d.prompt.getAsJsonArray("targets");
            check(targets.get(0).getAsJsonObject().get("lethal").getAsInt() == 1, "Deathtouch lethal was not one");
            check(targets.get(1).getAsJsonObject().get("lethal").getAsInt() == 3, "Planeswalker lethal did not use loyalty");
            d.rejects(d.action(1, 1, 3), "deathtouch treating loyalty as one");
            d.accepts(d.action(1, 3, 1));
        }
        try (Decision d = new Decision()) {
            CardView hidden = card(15, "Secret card", 3);
            hidden.set(TrackableProperty.Zone, ZoneType.Exile);
            hidden.set(TrackableProperty.Facedown, true);
            hidden.set(TrackableProperty.Controller, defender);
            LinkedHashMap<Object,Integer> targets = new LinkedHashMap<>();
            targets.put(hidden, 2); targets.put(MagicColor.Color.BLUE, null); targets.put(defender, 3);
            d.start(() -> d.gui.assignGenericAmount(hidden, targets, 4, true, "counters"));
            check(!d.session.snapshot.contains("Secret card") && d.session.snapshot.contains("Face-down card"), "Hidden allocation source or target leaked");
            d.rejects(d.action(0, 2, 2), "missing minimum-one allocation");
            d.rejects(d.action(3, 0, 1), "over-cap allocation");
            for (String literal : List.of("0.5", "2147483648", "1e1000", "\"1\"", "null", "true")) {
                JsonObject malformed = d.action(1, 1, 2);
                malformed.getAsJsonArray("allocations").get(0).getAsJsonObject().add("amount", JsonParser.parseString(literal));
                d.rejects(malformed, "malformed amount " + literal);
            }
            JsonObject duplicate = d.action(1, 1, 2);
            duplicate.getAsJsonArray("allocations").get(1).getAsJsonObject().add("id", duplicate.getAsJsonArray("allocations").get(0).getAsJsonObject().get("id"));
            d.rejects(duplicate, "duplicate target");
            JsonObject unknown = d.action(1, 1, 2);
            unknown.getAsJsonArray("allocations").get(0).getAsJsonObject().addProperty("id", "unknown");
            d.rejects(unknown, "unknown target");
            d.rejects(d.action(1, 3), "missing target");
            Map<?,?> result = d.accepts(d.action(1, 1, 2));
            check(result.get(hidden).equals(1) && result.get(MagicColor.Color.BLUE).equals(1) && result.get(defender).equals(2), "Generic map lost original card, mana, or player objects");
        }
        try (Decision d = new Decision()) {
            LinkedHashMap<Object,Integer> targets = new LinkedHashMap<>();
            targets.put(MagicColor.Color.BLUE, null); targets.put(MagicColor.Color.RED, null);
            d.start(() -> d.gui.assignGenericAmount(null, targets, Integer.MAX_VALUE, false, "mana"));
            d.rejects(d.action(Integer.MAX_VALUE, Integer.MAX_VALUE), "overflowing total");
            Map<?,?> result = d.accepts(d.action(0, Integer.MAX_VALUE));
            check(result.size() == 2 && result.get(MagicColor.Color.BLUE).equals(0), "Zero allocation entry was omitted");
        }
        System.out.println("Passed " + checks + " allocation checks through ProtocolGuiGame and the bridge");
    }
}
