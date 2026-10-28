package forge.browser;

import com.google.gson.*;
import forge.deck.Deck;
import forge.game.*;
import forge.game.player.*;
import forge.gamemodes.net.ProtocolMethod;
import forge.gamemodes.net.event.GuiGameEvent;
import forge.player.LobbyPlayerHuman;
import forge.player.PlayerControllerHuman;
import java.util.*;

public class CompletionTest {
    static int checks;
    static void check(boolean value, String message) {
        checks++;
        if (!value) throw new AssertionError(message);
    }
    static final class Seat extends LobbyPlayerHuman {
        Seat(String name) { super(name); }
        @Override public Player createIngamePlayer(Game game, int id) {
            Player player = new Player(getName(), game, id);
            player.setFirstController(new PlayerControllerHuman(game, player, this));
            return player;
        }
    }
    record Fixture(Game game, List<Player> players) {
        Fixture(PlayerOutcome... outcomes) {
            this(create(outcomes.length), new ArrayList<>());
            players.addAll(game.getRegisteredPlayers());
            for (int i = 0; i < outcomes.length; i++) players.get(i).getStats().setOutcome(outcomes[i]);
        }
        static Game create(int count) {
            List<RegisteredPlayer> seats = new ArrayList<>();
            for (int i = 0; i < count; i++) seats.add(new RegisteredPlayer(new Deck("Private deck " + i))
                    .setPlayer(new Seat(i == 0 ? "You" : i == 1 ? "CPU" : "Other")));
            GameRules rules = new GameRules(GameType.Commander);
            rules.setGamesPerMatch(1);
            return new Match(rules, seats, "Completion fixture").createGame();
        }
        GameOutcome outcome(GameEndReason reason) {
            GameOutcome outcome = new GameOutcome(reason, game.getRegisteredPlayers());
            outcome.setTurnsPlayed(13);
            return outcome;
        }
    }
    static void projection() {
        check(Bridge.CompletionResult.from(null) == null, "Missing outcome became result");
        check(Bridge.CompletionResult.from(new GameOutcome(GameEndReason.Draw, List.of())) == null, "Empty outcome became draw");
        Fixture decided = new Fixture(PlayerOutcome.altWin("Private source name"), PlayerOutcome.loss(GameLossReason.OpponentWon, "Hidden spell name"));
        GameOutcome outcome = decided.outcome(GameEndReason.WinsGameSpellEffect);
        Bridge.CompletionResult result = Bridge.CompletionResult.from(outcome);
        check(result.kind().equals("decided") && result.turns() == 13, "Decided result or turn count lost");
        check(result.participants().get(0).name().equals("You") && result.participants().get(0).outcome().equals("won"), "Winner or deterministic order lost");
        check(result.participants().get(1).lossReason().equals("OpponentWon"), "Loser reason lost");
        String json = Bridge.JSON.toJson(result);
        check(!json.contains("Private") && !json.contains("Hidden") && !json.contains("deck"), "Result leaks engine source data");
        check(Bridge.CompletionResult.from(outcome).equals(result), "Repeated projection changed result");
        Fixture conceded = new Fixture(PlayerOutcome.concede(), PlayerOutcome.win());
        result = Bridge.CompletionResult.from(conceded.outcome(GameEndReason.AllOpponentsLost));
        check(result.participants().get(0).lossReason().equals("Conceded"), "Concession became natural loss");
        Fixture drawn = new Fixture(PlayerOutcome.loss(GameLossReason.CommanderDamage, null), PlayerOutcome.draw(), PlayerOutcome.draw());
        result = Bridge.CompletionResult.from(drawn.outcome(GameEndReason.Draw));
        check(result.kind().equals("draw") && result.participants().size() == 3, "Complete draw participants lost");
        check(result.participants().get(0).outcome().equals("lost"), "Prior loser became draw");
        check(result.participants().stream().filter(p -> p.outcome().equals("draw")).count() == 2, "Draw participants lost");
        Fixture allLost = new Fixture(PlayerOutcome.loss(GameLossReason.LifeReachedZero, null), PlayerOutcome.loss(GameLossReason.Milled, null));
        result = Bridge.CompletionResult.from(allLost.outcome(GameEndReason.Draw));
        check(result.kind().equals("draw") && result.participants().stream().allMatch(p -> p.outcome().equals("lost")), "Engine all-losers draw changed");
        outcome.getPlayerNames().remove(decided.players().get(1).getRegisteredPlayer());
        check(Bridge.CompletionResult.from(outcome) == null, "Missing participant name produced partial result");
        outcome = conceded.outcome(GameEndReason.AllOpponentsLost);
        conceded.players().get(0).getStats().setOutcome(null);
        check(Bridge.CompletionResult.from(outcome) == null, "Incomplete statistics produced draw");
    }
    static void lifecycle() {
        Fixture fixture = new Fixture(PlayerOutcome.loss(GameLossReason.LifeReachedZero, null), PlayerOutcome.win());
        fixture.game().getPlayers().remove(fixture.players().get(0));
        fixture.game().getView().updatePlayers(fixture.game());
        fixture.game().setGameOver(GameEndReason.AllOpponentsLost);
        Bridge.MatchSession session = new Bridge.MatchSession(new JsonObject());
        session.gui = new Bridge.PumpGui(session);
        session.gui.setGameView(fixture.game().getView());
        session.human = fixture.players().get(0).getView();
        session.status = "playing";
        session.newPrompt("input", "Old pending action");
        session.input = new Bridge.TextInput("Title", "", null, false);
        session.inFlight = true;
        session.publish();
        JsonObject first = JsonParser.parseString(session.snapshot).getAsJsonObject();
        check(first.get("status").getAsString().equals("finished") && first.has("result"), "Natural engine result not captured");
        check(first.getAsJsonArray("players").size() == 1 && first.getAsJsonObject("result").getAsJsonArray("participants").size() == 2, "Eliminated participant disappeared from result");
        check(!first.has("prompt") && session.promptId == null && session.promptKind == null && session.input == null && !session.inFlight, "Terminal prompt state survived");
        session.send(new GuiGameEvent(ProtocolMethod.updateButtons, session.human, "Old OK", "Old cancel", true, true, true));
        check(!JsonParser.parseString(session.snapshot).getAsJsonObject().has("prompt"), "Late button event revived interaction");
        session.gui.setGameView(null);
        session.send(new GuiGameEvent(ProtocolMethod.finishGame));
        session.send(new GuiGameEvent(ProtocolMethod.afterGameEnd));
        JsonObject repeated = JsonParser.parseString(session.snapshot).getAsJsonObject();
        check(repeated.get("result").equals(first.get("result")), "Cleanup lost or changed authoritative result");
        check(session.submit(new JsonObject()) != null, "Finished match accepted another action");
        Bridge.MatchSession noOutcome = new Bridge.MatchSession(new JsonObject());
        noOutcome.send(new GuiGameEvent(ProtocolMethod.finishGame));
        check(!JsonParser.parseString(noOutcome.snapshot).getAsJsonObject().has("result"), "Finished without outcome became draw");
        noOutcome.status = "error"; noOutcome.error = "Unsupported decision";
        noOutcome.send(new GuiGameEvent(ProtocolMethod.finishGame));
        check(JsonParser.parseString(noOutcome.snapshot).getAsJsonObject().get("status").getAsString().equals("error"), "Terminal callback erased error");
        Bridge.MatchSession fresh = new Bridge.MatchSession(new JsonObject());
        check(fresh.result == null && !JsonParser.parseString(fresh.snapshot).getAsJsonObject().has("result"), "New match inherited result");
    }
    public static void main(String[] args) {
        forge.util.Localizer.getInstance().initialize("en-US", "forge-gui/res/languages");
        projection(); lifecycle();
        System.out.println("Passed " + checks + " authoritative completion and terminal lifecycle checks");
    }
}
