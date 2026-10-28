package forge.browser;

import com.google.gson.*;
import forge.game.card.CardView;
import forge.game.player.PlayerView;
import forge.game.zone.ZoneType;
import forge.trackable.TrackableProperty;
import java.util.*;
import java.util.concurrent.*;

public class InputTest {
    static int checks;
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
        void start(Callable<?> task, String kind) throws Exception {
            result = worker.submit(task);
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
            do {
                snapshot = JsonParser.parseString(session.snapshot).getAsJsonObject();
                if (snapshot.has("prompt")) {
                    prompt = snapshot.getAsJsonObject("prompt");
                    check(prompt.get("kind").getAsString().equals(kind), "Wrong prompt kind");
                    return;
                }
                if (result.isDone()) result.get();
                Thread.sleep(5);
            } while (System.nanoTime() < deadline);
            throw new AssertionError("Input prompt did not appear");
        }
        JsonObject action(String kind) {
            JsonObject action = new JsonObject();
            action.addProperty("matchId", session.id);
            action.add("revision", snapshot.get("revision"));
            action.add("promptId", prompt.get("id"));
            action.addProperty("kind", kind);
            return action;
        }
        JsonObject order(int... indices) {
            JsonObject action = action("manipulate");
            JsonArray ids = new JsonArray();
            for (int index : indices) ids.add(prompt.getAsJsonArray("cards").get(index).getAsJsonObject().get("id"));
            action.add("cardIds", ids);
            return action;
        }
        void rejects(JsonObject action, String reason) {
            check(session.submit(action) != null, "Accepted " + reason);
            check(!result.isDone(), "Rejected answer completed the prompt");
        }
        Object accepts(JsonObject action) throws Exception {
            check(session.submit(action) == null, "Rejected valid answer");
            check(session.submit(action) != null, "Accepted duplicate answer");
            return result.get(5, TimeUnit.SECONDS);
        }
        @Override public void close() { worker.shutdownNow(); }
    }
    static void text() throws Exception {
        for (String value : List.of("", "  0007  ", "<img src=x onerror=alert(1)>", "文字")) {
            try (Decision d = new Decision()) {
                d.start(() -> d.gui.showInputDialog("Value", "Input", null, "initial", null, true), "input");
                check(d.prompt.get("initial").getAsString().equals("initial"), "Initial text lost");
                check(d.prompt.get("numeric").getAsBoolean(), "Numeric hint lost");
                JsonObject a = d.action("input"); a.addProperty("value", value);
                for (String invalid : List.of("null", "true", "7", "[]", "{}")) {
                    JsonObject malformed = a.deepCopy(); malformed.add("value", JsonParser.parseString(invalid));
                    d.rejects(malformed, "non-string text");
                }
                JsonObject stale = a.deepCopy(); stale.addProperty("revision", 0); d.rejects(stale, "stale revision");
                stale = a.deepCopy(); stale.addProperty("promptId", "old"); d.rejects(stale, "stale prompt");
                d.rejects(d.action("ok"), "ordinary OK");
                check(value.equals(d.accepts(a)), "Text changed or empty text became cancellation");
            }
        }
        try (Decision d = new Decision()) {
            d.start(() -> d.gui.showInputDialog("Value", "Input", null, null, null, false), "input");
            check(d.prompt.get("initial").getAsString().isEmpty(), "Null initial text was not empty");
            check(d.accepts(d.action("cancel")) == null, "Cancel did not return null");
        }
        try (Decision d = new Decision()) {
            List<String> options = List.of("Red", "", "Red");
            d.start(() -> d.gui.showInputDialog("Color", "Select", null, "Red", options, false), "input");
            JsonArray published = d.prompt.getAsJsonArray("options");
            check(published.size() == 3, "Options lost");
            check(!published.get(0).getAsJsonObject().get("id").equals(published.get(2).getAsJsonObject().get("id")), "Duplicate labels share IDs");
            JsonObject a = d.action("input"); a.addProperty("value", "Red"); d.rejects(a, "unrestricted option text");
            a.addProperty("optionId", "unknown"); d.rejects(a, "unknown option");
            a.add("optionId", published.get(1).getAsJsonObject().get("id"));
            check("".equals(d.accepts(a)), "Empty option did not return its original value");
        }
        try (Decision d = new Decision()) {
            d.start(() -> d.gui.showInputDialog("None", "Select", null, "", List.of(), false), "input");
            check(d.prompt.getAsJsonArray("options").isEmpty(), "Empty options became free text");
            JsonObject a = d.action("input"); a.addProperty("value", ""); d.rejects(a, "text for empty option list");
            check(d.accepts(d.action("cancel")) == null, "Empty-option cancellation failed");
        }
    }
    static void cards() throws Exception {
        CardView a = new CardView(10, null, "A"), b = new CardView(11, null, "B"),
                c = new CardView(12, null, "Hidden library card"), d = new CardView(13, null, "D");
        c.set(TrackableProperty.Zone, ZoneType.Library);
        c.set(TrackableProperty.Controller, new PlayerView(2, null));
        List<CardView> originals = List.of(a, b, c, d);
        try (Decision q = new Decision()) {
            q.start(() -> q.gui.manipulateCardList("Scry", originals, List.of(a, d, new CardView(99, null, "Foreign")), true, true, false), "manipulate");
            check(!q.session.snapshot.contains("Hidden library card") && !q.session.snapshot.contains("Foreign"), "Hidden or foreign card leaked");
            check(q.prompt.getAsJsonArray("cards").get(2).getAsJsonObject().get("label").getAsString().equals("Face-down card"), "Hidden card label wrong");
            q.rejects(q.order(0, 1, 3), "missing fixed card");
            q.rejects(q.order(0, 1, 2, 2), "duplicate card");
            q.rejects(q.order(0, 2, 1, 3), "reordered fixed cards");
            q.rejects(q.order(1, 0, 2, 3), "movable card inside fixed middle");
            q.rejects(q.action("cancel"), "card-list cancellation");
            JsonObject malformed = q.order(0, 1, 2, 3); malformed.getAsJsonArray("cardIds").set(0, new JsonPrimitive(10));
            q.rejects(malformed, "numeric card ID");
            List<?> result = (List<?>)q.accepts(q.order(3, 0, 1, 2));
            check(result.size() == 4 && result.get(0) == d && result.get(1) == a && result.get(2) == b && result.get(3) == c,
                    "Complete list did not preserve original identities");
        }
        for (int flags = 0; flags < 8; flags++) {
            final int f = flags;
            try (Decision q = new Decision()) {
                q.start(() -> q.gui.manipulateCardList("Order", originals, List.of(a, d), (f & 1) != 0, (f & 2) != 0, (f & 4) != 0), "manipulate");
                if ((f & 4) == 0) q.rejects(q.order(1, 0, 2, 3), "interior movement without anywhere");
                List<?> result = (List<?>)q.accepts((f & 4) == 0 ? q.order(0, 1, 2, 3) : q.order(1, 0, 2, 3));
                check(result.size() == originals.size(), "Flags changed list cardinality");
            }
        }
        try (Decision q = new Decision()) {
            q.start(() -> q.gui.manipulateCardList("Empty", List.of(), List.of(), false, false, false), "manipulate");
            check(((List<?>)q.accepts(q.order())).isEmpty(), "Empty list failed");
        }
    }
    static boolean desktopMove(List<Integer> order, int mask, int old, int index, boolean top, boolean bottom) {
        boolean topMove = true;
        for (int i = 0; i < index + (old < index ? 1 : 0); i++)
            if ((mask & (1 << order.get(i))) == 0) { topMove = false; break; }
        if (top && topMove) return true;
        boolean bottomMove = true;
        for (int i = index + 1 - (old > index ? 1 : 0); i < order.size(); i++)
            if ((mask & (1 << order.get(i))) == 0) { bottomMove = false; break; }
        return bottom && bottomMove;
    }
    static Set<List<Integer>> reachable(int n, int mask, boolean top, boolean bottom) {
        List<Integer> original = new ArrayList<>(); for (int i = 0; i < n; i++) original.add(i);
        Set<List<Integer>> seen = new HashSet<>(); seen.add(original);
        ArrayDeque<List<Integer>> queue = new ArrayDeque<>(); queue.add(original);
        while (!queue.isEmpty()) {
            List<Integer> order = queue.remove();
            for (int old = 0; old < n; old++) if ((mask & (1 << order.get(old))) != 0)
                for (int index = 0; index < n; index++) if (desktopMove(order, mask, old, index, top, bottom)) {
                    List<Integer> next = new ArrayList<>(order); int card = next.remove(old); next.add(index, card);
                    if (seen.add(next)) queue.add(next);
                }
        }
        return seen;
    }
    static void permutations(List<Integer> entries, int index, List<List<Integer>> out) {
        if (index == entries.size()) { out.add(List.copyOf(entries)); return; }
        for (int i = index; i < entries.size(); i++) {
            Collections.swap(entries, index, i); permutations(entries, index + 1, out); Collections.swap(entries, index, i);
        }
    }
    static void reachability() {
        int comparisons = 0;
        for (int n = 0; n <= 6; n++) {
            List<Integer> indices = new ArrayList<>(); for (int i = 0; i < n; i++) indices.add(i);
            List<List<Integer>> permutations = new ArrayList<>(); permutations(indices, 0, permutations);
            for (int mask = 0; mask < (1 << n); mask++) for (int flags = 0; flags < 4; flags++) {
                List<Bridge.ManipulationCard> cards = new ArrayList<>();
                for (int i = 0; i < n; i++) cards.add(new Bridge.ManipulationCard("card-" + i, null, "Card", (mask & (1 << i)) != 0));
                Bridge.CardManipulation model = new Bridge.CardManipulation(cards, (flags & 1) != 0, (flags & 2) != 0, false);
                Set<List<Integer>> reachable = reachable(n, mask, model.toTop(), model.toBottom());
                for (List<Integer> permutation : permutations) {
                    boolean accepted = model.permits(permutation.stream().map(cards::get).toList());
                    check(accepted == reachable.contains(permutation), "Endpoint reachability mismatch for " + indices + ", mask " + mask + ", flags " + flags + ", result " + permutation);
                    comparisons++;
                }
            }
        }
        System.out.println("Passed " + comparisons + " endpoint comparisons against desktop legal-move exploration");
    }
    public static void main(String[] args) throws Exception {
        text(); cards(); reachability();
        System.out.println("Passed " + checks + " input and card-list checks through ProtocolGuiGame and the bridge");
    }
}
