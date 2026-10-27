package forge.browser;

import com.google.gson.*;
import forge.gamemodes.net.ProtocolMethod;
import forge.gamemodes.net.event.GuiGameEvent;
import forge.gui.interfaces.IGuiGame.OrderResult;
import java.util.*;
import java.util.concurrent.*;

public class PromptTest {
    public static void main(String[] args) throws Exception {
        Bridge.MatchSession session = new Bridge.MatchSession(new JsonObject());
        Object first = new Object(), second = new Object(), third = new Object();
        GuiGameEvent event = new GuiGameEvent(ProtocolMethod.order, "Order", "First", 0, 0,
                List.of(first, second, third), null, null, false, false);
        ExecutorService worker = Executors.newSingleThreadExecutor();
        try {
            Future<Object> result = worker.submit(() -> session.sendAndWait(event));
            JsonObject snapshot;
            do {
                Thread.sleep(10);
                snapshot = JsonParser.parseString(session.snapshot).getAsJsonObject();
            } while (!snapshot.has("prompt"));
            JsonObject prompt = snapshot.getAsJsonObject("prompt");
            if (!prompt.get("kind").getAsString().equals("order")) throw new AssertionError("Expected order prompt");
            JsonArray options = prompt.getAsJsonArray("choices");
            JsonArray ids = new JsonArray();
            for (int i : new int[]{2, 0, 1}) ids.add(options.get(i).getAsJsonObject().get("id").getAsString());
            JsonObject action = new JsonObject();
            action.addProperty("matchId", session.id);
            action.addProperty("revision", snapshot.get("revision").getAsLong());
            action.addProperty("promptId", prompt.get("id").getAsString());
            action.addProperty("kind", "choice"); action.add("choiceIds", ids);
            JsonObject invalid = action.deepCopy();
            JsonArray badIds = new JsonArray(); badIds.add("unknown"); invalid.add("choiceIds", badIds);
            if (session.submit(invalid) == null) throw new AssertionError("Invalid order accepted");
            if (session.submit(action) != null) throw new AssertionError("Order rejected");
            OrderResult<?> order = (OrderResult<?>)result.get(5, TimeUnit.SECONDS);
            if (!order.ordered().equals(List.of(third, first, second))) throw new AssertionError("Wrong objects or order");
            System.out.println("Passed: order returns the original objects in the chosen order");
        } finally { worker.shutdownNow(); }
    }
}
