package forge.browser;

import com.google.common.collect.HashMultiset;
import com.google.gson.*;
import forge.card.CardStateName;
import forge.card.CardType;
import forge.game.card.CardView;
import forge.game.card.CounterEnumType;
import forge.game.card.CounterType;
import forge.game.player.PlayerView;
import forge.game.zone.ZoneType;
import forge.trackable.TrackableProperty;
import java.util.*;

public class CardPresentationTest {
    static int checks;
    static void check(boolean value, String message) {
        checks++;
        if (!value) throw new AssertionError(message);
    }
    static CardView card(int id, String name, PlayerView controller, String type) {
        CardView card = new CardView(id, null, name);
        card.set(TrackableProperty.Controller, controller);
        card.set(TrackableProperty.Owner, controller);
        card.set(TrackableProperty.Zone, ZoneType.Battlefield);
        card.getCurrentState().set(TrackableProperty.Type, new CardType(List.of(type), true));
        return card;
    }
    static JsonObject project(Bridge.SeatView seat, CardView card) {
        return Bridge.JSON.toJsonTree(seat.zone(List.of(card))).getAsJsonArray().get(0).getAsJsonObject();
    }
    public static void main(String[] args) {
        Bridge.SeatView seat = new Bridge.SeatView(new JsonObject(), null, 0);
        PlayerView self = new PlayerView(1, null), opponent = new PlayerView(2, null);
        seat.human = self;
        CardView creature = card(10, "Visible creature", self, "Creature");
        creature.getCurrentState().set(TrackableProperty.Power, 5);
        creature.getCurrentState().set(TrackableProperty.Toughness, 7);
        creature.set(TrackableProperty.Tapped, true);
        creature.set(TrackableProperty.Attacking, true);
        creature.set(TrackableProperty.Token, true);
        var counters = HashMultiset.<CounterType>create();
        counters.add(CounterEnumType.P1P1, 3);
        counters.add(CounterEnumType.STUN, 2);
        creature.set(TrackableProperty.Counters, counters);
        JsonObject visible = project(seat, creature);
        check(visible.get("pt").getAsString().equals("5/7"), "Current creature stats omitted");
        check(visible.get("tapped").getAsBoolean() && visible.get("attacking").getAsBoolean()
                && visible.get("token").getAsBoolean() && !visible.get("blocking").getAsBoolean(), "Public state flags changed");
        check(visible.getAsJsonObject("counters").get("+1/+1").getAsInt() == 3
                && visible.getAsJsonObject("counters").get(CounterEnumType.STUN.getName()).getAsInt() == 2, "Counter labels or amounts changed");
        check(visible.get("artName").getAsString().equals("Visible creature"), "Artwork name fallback lost");
        check(seat.cards.get("10") == creature, "Action card identity changed");
        creature.getCurrentState().set(TrackableProperty.Power, 8);
        creature.set(TrackableProperty.Attacking, false);
        creature.set(TrackableProperty.Blocking, true);
        check(project(seat, creature).get("pt").getAsString().equals("8/7"), "Projection reused stale stats");
        check(project(seat, creature).get("blocking").getAsBoolean()
                && !project(seat, creature).get("attacking").getAsBoolean(), "Combat changes not projected");
        CardView land = card(11, "Island", self, "Land");
        JsonObject landView = project(seat, land);
        check(!landView.has("pt") && landView.getAsJsonObject("counters").size() == 0, "Noncreature has invented stats or counters");
        var transformed = creature.createAlternateState(CardStateName.Backside);
        transformed.set(TrackableProperty.Name, "Back-face display name");
        transformed.set(TrackableProperty.OracleName, "Back-face Oracle name");
        transformed.set(TrackableProperty.Type, new CardType(List.of("Creature"), true));
        transformed.set(TrackableProperty.Power, 9);
        transformed.set(TrackableProperty.Toughness, 9);
        creature.set(TrackableProperty.CurrentState, transformed);
        JsonObject back = project(seat, creature);
        check(back.get("name").getAsString().equals("Visible creature"), "Existing display name contract changed");
        check(back.get("artName").getAsString().equals("Back-face Oracle name")
                && back.get("pt").getAsString().equals("9/9"), "Transformed face artwork or stats use original state");
        CardView hidden = card(12, "Secret morph identity", opponent, "Creature");
        hidden.set(TrackableProperty.Facedown, true);
        hidden.set(TrackableProperty.Tapped, true);
        hidden.set(TrackableProperty.Counters, counters);
        check(hidden.canBeShownTo(self) && !hidden.canFaceDownBeShownTo(self), "Fixture does not exercise public face-down visibility boundary");
        JsonObject concealed = project(seat, hidden);
        check(concealed.keySet().equals(Set.of("id", "name", "tapped", "faceDown")), "Hidden battlefield card leaked presentation fields");
        check(concealed.get("name").getAsString().equals("Face-down card")
                && concealed.get("faceDown").getAsBoolean() && concealed.get("tapped").getAsBoolean(), "Hidden card lost safe public state");
        check(!concealed.toString().contains("Secret"), "Hidden identity leaked");
        seat.human = opponent;
        JsonObject ownFaceDown = project(seat, hidden);
        check(ownFaceDown.has("type") && ownFaceDown.has("text") && !ownFaceDown.has("artName")
                && ownFaceDown.get("faceDown").getAsBoolean(), "Owner visibility changed or face-down artwork requested");
        seat.human = self;
        hidden.set(TrackableProperty.Facedown, false);
        hidden.set(TrackableProperty.Zone, ZoneType.Hand);
        check(project(seat, hidden).keySet().equals(Set.of("id", "name", "tapped", "faceDown")), "Opponent hand card leaked identity");
        check(seat.cards.get("12") == hidden, "Hidden action card identity changed");
        System.out.println("Passed " + checks + " real CardView presentation and privacy checks");
    }
}
