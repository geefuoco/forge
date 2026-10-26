import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.common.eventbus.Subscribe;
import forge.GuiDesktop;
import forge.deck.CardPool;
import forge.deck.Deck;
import forge.deck.DeckFormat;
import forge.deck.DeckSection;
import forge.deck.io.DeckSerializer;
import forge.game.Game;
import forge.game.GameOutcome;
import forge.game.GameRules;
import forge.game.GameType;
import forge.game.Match;
import forge.game.event.GameEvent;
import forge.game.event.GameEventGameStarted;
import forge.game.player.RegisteredPlayer;
import forge.gui.GuiBase;
import forge.localinstance.properties.ForgeConstants;
import forge.localinstance.properties.ForgePreferences;
import forge.model.FModel;
import forge.player.GamePlayerUtil;
import forge.util.MyRandom;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.EnumSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.Observable;
import java.util.Observer;

public final class CommanderEval {
    private static final Gson JSON = new GsonBuilder().setPrettyPrinting().create();
    private static final int SCHEMA_VERSION = 1;

    private record Seat(String deckId, String deckFile, String commander, int totalCards, String expectedSha256) {}
    private record GameRequest(int schema_version, String mode, String id, long seed,
                               List<Seat> seats, String profile, String monte_carlo,
                               int ai_timeout_seconds, String output_directory,
                               String assets_directory, String resource_root) {}
    private static final class RejectedInputException extends RuntimeException {
        private static final long serialVersionUID = 1L;
        RejectedInputException(String message) { super(message); }
    }

    private CommanderEval() {}

    public static void main(String[] args) {
        try {
            if (args.length == 2 && args[0].equals("--play")) {
                startDesktop(Path.of(args[1]));
                return;
            }
            if (args.length != 1) throw new RejectedInputException("usage: CommanderEval request.json");
            GameRequest request = readRequest(Path.of(args[0]));
            prepareAssets(request);
            System.setProperty("java.awt.headless", "true");
            GuiBase.setInterface(new GuiDesktop() {
                @Override public String getAssetsDir() { return Path.of(request.assets_directory()).toAbsolutePath() + java.io.File.separator; }
            });
            Path outputDirectory = Path.of(request.output_directory());
            Path assetsDirectory = Path.of(request.assets_directory());
            Path profileFile = assetsDirectory.resolve("forge.profile.properties");
            Map<String, Object> paths = Map.of(
                    "user", ForgeConstants.USER_DIR,
                    "cache", ForgeConstants.CACHE_DIR,
                    "decks", ForgeConstants.DECK_BASE_DIR,
                    "logs", ForgeConstants.LOG_FILE);
            for (Object value : paths.values()) assertContained(outputDirectory, Path.of(value.toString()));
            FModel.initialize(null, preferences -> {
                preferences.setPref(ForgePreferences.FPref.UI_ENABLE_AI_CHEATS, "false");
                preferences.setPref(ForgePreferences.FPref.FILTERED_HANDS, "false");
                preferences.setPref(ForgePreferences.FPref.MATCH_AI_TIMEOUT, Integer.toString(request.ai_timeout_seconds()));
                preferences.setPref(ForgePreferences.FPref.MATCH_AI_FLAT_MONTE_CARLO,
                        Boolean.toString(!request.monte_carlo().equals("off")));
                preferences.setPref(ForgePreferences.FPref.UI_CURRENT_AI_PROFILE, request.profile());
                return null;
            });
            List<Deck> decks = new ArrayList<>();
            for (Seat seat : request.seats()) decks.add(loadVerifiedCommanderDeck(seat));
            writeJson(outputDirectory.resolve("setup.json"), Map.of(
                    "schema_version", SCHEMA_VERSION, "request_id", request.id(), "status", "ready",
                    "profile_file_sha256", sha256(profileFile), "effective_ai", Map.of(
                            "profile", request.profile(), "monte_carlo", request.monte_carlo(),
                            "ai_timeout_seconds", request.ai_timeout_seconds(), "cheats", false,
                            "filtered_hands", false), "paths", paths,
                    "seats", List.of(seatReceipt(request.seats().get(0), decks.get(0)),
                            seatReceipt(request.seats().get(1), decks.get(1)))));
            if (request.mode().equals("validate")) return;

            List<RegisteredPlayer> players = List.of(
                    RegisteredPlayer.forCommander(decks.get(0)),
                    RegisteredPlayer.forCommander(decks.get(1)));
            if (players.size() != 2 || players.stream().anyMatch(p -> p.getStartingLife() != 40)) {
                throw new IllegalStateException("Commander game must have two seats at 40 life");
            }
            for (int i = 0; i < players.size(); i++) {
                players.get(i).setPlayer(GamePlayerUtil.createAiPlayer("Eval seat " + i, 0, 0, null, request.profile()));
            }
            GameRules rules = new GameRules(GameType.Commander);
            rules.setAppliedVariants(EnumSet.of(GameType.Commander));
            Match match = new Match(rules, players, "Neo Forge evaluation " + request.id());
            Game game;
            MyRandom.setRandom(new Random(request.seed()));
            game = match.createGame();
            game.setNoGUIUser();
            game.AI_TIMEOUT = request.ai_timeout_seconds();
            game.AI_FLAT_MONTE_CARLO = !request.monte_carlo().equals("off");
            game.AI_FLAT_MONTE_CARLO_MAX = request.monte_carlo().equals("desktop-max");
            final int[] firstSeat = {-1};
            game.subscribeToEvents(new Object() {
                @Subscribe public void receive(GameEvent event) {
                    if (!(event instanceof GameEventGameStarted started)) return;
                    for (int i = 0; i < players.size(); i++) {
                        if (players.get(i).getPlayer().getName().equals(started.firstTurn().getName())) firstSeat[0] = i;
                    }
                }
            });
            Path gameLogPath = outputDirectory.resolve("game.log");
            java.util.concurrent.atomic.AtomicInteger written = new java.util.concurrent.atomic.AtomicInteger();
            Observer logWriter = (Observable source, Object event) -> {
                List<forge.game.GameLogEntry> entries = game.getGameLog().getAllEntries();
                int from = written.getAndSet(entries.size());
                if (from >= entries.size()) return;
                List<String> lines = entries.subList(from, entries.size()).stream()
                        .map(entry -> entry.type() + "\t" + entry.message()).toList();
                try { Files.write(gameLogPath, lines, java.nio.file.StandardOpenOption.CREATE, java.nio.file.StandardOpenOption.APPEND); }
                catch (IOException ex) { throw new IllegalStateException("cannot persist game log", ex); }
            };
            game.getGameLog().addObserver(logWriter);
            writeJson(outputDirectory.resolve("started.json"), Map.of(
                    "schema_version", SCHEMA_VERSION, "request_id", request.id(), "status", "started"));
            match.startGame(game);
            if (!game.isGameOver() || game.getOutcome() == null) {
                throw new IllegalStateException("Match.startGame returned without a natural terminal outcome");
            }
            GameOutcome outcome = game.getOutcome();
            String terminal = outcome.isDraw() ? "draw" : "win";
            int winnerSeat = -1;
            if (terminal.equals("win")) {
                for (int i = 0; i < players.size(); i++) {
                    if (outcome.isWinner(players.get(i))) winnerSeat = i;
                }
                if (winnerSeat < 0) throw new IllegalStateException("Engine reported a winner outside the two registered seats");
            }
            game.getGameLog().deleteObserver(logWriter);
            List<forge.game.GameLogEntry> entries = game.getGameLog().getAllEntries();
            int writtenCount = written.get();
            if (writtenCount < entries.size()) {
                List<String> remaining = entries.subList(writtenCount, entries.size()).stream()
                        .map(entry -> entry.type() + "\t" + entry.message()).toList();
                Files.write(gameLogPath, remaining, java.nio.file.StandardOpenOption.CREATE, java.nio.file.StandardOpenOption.APPEND);
            }
            writeJson(outputDirectory.resolve("terminal.json"), Map.of(
                    "schema_version", SCHEMA_VERSION, "request_id", request.id(), "status", "terminal",
                    "terminal", terminal, "winner_seat", winnerSeat,
                    "engine_end_reason", outcome.getWinCondition().name(),
                    "last_turn", outcome.getLastTurnNumber(), "first_player_seat", firstSeat[0],
                    "game_log", "game.log", "commander_life", List.of(players.get(0).getStartingLife(), players.get(1).getStartingLife())));
        } catch (Throwable failure) {
            try {
                if (args.length > 0) {
                    GameRequest request = JSON.fromJson(Files.readString(Path.of(args[0])), GameRequest.class);
                    if (request != null && request.output_directory() != null) {
                        writeJson(Path.of(request.output_directory()).resolve("failure.json"), Map.of(
                                "schema_version", SCHEMA_VERSION, "request_id", request.id() == null ? "" : request.id(),
                                "classification", failure instanceof RejectedInputException ? "rejected" : "crashed",
                                "type", failure.getClass().getName(), "message", String.valueOf(failure.getMessage())));
                    }
                }
            } catch (Throwable ignored) { }
            failure.printStackTrace(System.err);
            System.exit(failure instanceof RejectedInputException ? 2 : 1);
        }
    }

    private static GameRequest readRequest(Path path) throws IOException {
        GameRequest request = JSON.fromJson(Files.readString(path), GameRequest.class);
        if (request == null || request.schema_version() != SCHEMA_VERSION ||
                !("validate".equals(request.mode()) || "evaluate".equals(request.mode())) ||
                request.id() == null || request.seats() == null || request.seats().size() != 2 ||
                request.profile() == null || !request.profile().equals("Default") ||
                !List.of("off", "standard", "desktop-max").contains(request.monte_carlo()) ||
                request.ai_timeout_seconds() < 1 || request.output_directory() == null ||
                request.assets_directory() == null || request.resource_root() == null) {
            throw new RejectedInputException("request is incomplete or contains unsupported settings");
        }
        return request;
    }

    private static void startDesktop(Path requestPath) throws IOException {
        System.setProperty("java.awt.headless", "false");
        GameRequest request = JSON.fromJson(Files.readString(requestPath), GameRequest.class);
        if (request == null || request.assets_directory() == null) throw new IllegalArgumentException("invalid desktop request");
        GuiBase.setInterface(new GuiDesktop() {
            @Override public String getAssetsDir() { return Path.of(request.assets_directory()).toAbsolutePath() + java.io.File.separator; }
        });
        Path root = requestPath.toAbsolutePath().getParent();
        for (String value : List.of(ForgeConstants.USER_DIR, ForgeConstants.CACHE_DIR,
                ForgeConstants.DECK_BASE_DIR, ForgeConstants.LOG_FILE)) {
            assertContained(root, Path.of(value));
        }
        ForgePreferences preferences = FModel.getPreferences();
        preferences.setPref(ForgePreferences.FPref.UI_ENABLE_AI_CHEATS, "false");
        preferences.setPref(ForgePreferences.FPref.FILTERED_HANDS, "false");
        preferences.setPref(ForgePreferences.FPref.UI_CURRENT_AI_PROFILE, request.profile());
        preferences.setPref(ForgePreferences.FPref.MATCH_AI_TIMEOUT, Integer.toString(request.ai_timeout_seconds()));
        preferences.setPref(ForgePreferences.FPref.MATCH_AI_FLAT_MONTE_CARLO,
                Boolean.toString(!request.monte_carlo().equals("off")));
        preferences.setPref(ForgePreferences.FPref.CHECK_SNAPSHOT_AT_STARTUP, false);
        forge.Singletons.initializeOnce(true);
        forge.Singletons.getControl().initialize();
        try {
            javax.swing.SwingUtilities.invokeAndWait(() -> {
                if (!forge.Singletons.getView().getFrame().isShowing()) {
                    throw new IllegalStateException("Forge desktop frame did not become visible");
                }
            });
        } catch (Exception failure) {
            throw new IOException("Forge desktop initialization failed", failure);
        }
        writeJson(root.resolve("desktop-started.json"), Map.of(
                "schema_version", SCHEMA_VERSION, "request_id", request.id(),
                "status", "desktop-started", "pid", ProcessHandle.current().pid(),
                "paths", Map.of("user", ForgeConstants.USER_DIR, "cache", ForgeConstants.CACHE_DIR,
                        "decks", ForgeConstants.DECK_BASE_DIR, "logs", ForgeConstants.LOG_FILE),
                "effective_ai", Map.of("profile", request.profile(), "monte_carlo", request.monte_carlo(),
                        "ai_timeout_seconds", request.ai_timeout_seconds(), "cheats", false, "filtered_hands", false)));
    }

    private static void prepareAssets(GameRequest request) throws IOException {
        Path assets = Path.of(request.assets_directory()).toAbsolutePath().normalize();
        Path resource = Path.of(request.resource_root()).toAbsolutePath().normalize();
        Path upstreamProfile = resource.getParent().resolve("forge.profile.properties");
        if (Files.exists(upstreamProfile)) throw new IllegalStateException("resource root has a profile override");
        Files.createDirectories(assets);
        Path res = assets.resolve("res");
        if (!Files.exists(res)) Files.createSymbolicLink(res, resource);
        Path output = Path.of(request.output_directory()).toAbsolutePath().normalize();
        Path user = output.resolve("profile").toAbsolutePath();
        Path cache = output.resolve("cache").toAbsolutePath();
        Files.createDirectories(user);
        Files.createDirectories(cache);
        Files.writeString(assets.resolve("forge.profile.properties"),
                "userDir=" + user.toString().replace("\\", "/") + "/\n" +
                "cacheDir=" + cache.toString().replace("\\", "/") + "/\n");
    }

    private static Deck loadVerifiedCommanderDeck(Seat seat) throws Exception {
        if (!sha256(Path.of(seat.deckFile())).equals(seat.expectedSha256())) {
            throw new RejectedInputException("staged fixture hash mismatch for " + seat.deckId());
        }
        Deck deck = DeckSerializer.fromFile(Path.of(seat.deckFile()).toFile());
        if (deck == null) throw new RejectedInputException("cannot parse deck " + seat.deckId());
        Map<String, Integer> actual = new LinkedHashMap<>();
        for (Map.Entry<DeckSection, CardPool> section : deck) {
            for (Map.Entry<forge.item.PaperCard, Integer> card : section.getValue()) {
                actual.merge(section.getKey().name() + "/" + card.getKey().getName(), card.getValue(), Integer::sum);
            }
        }
        Map<String, Integer> declared = declaredCards(Path.of(seat.deckFile()));
        if (!actual.equals(declared)) {
            throw new RejectedInputException("resolved card identities or counts differ from source for " + seat.deckId());
        }
        int total = actual.values().stream().mapToInt(Integer::intValue).sum();
        if (total != seat.totalCards() || deck.getCommanders().size() != 1 ||
                !deck.getCommanders().get(0).getName().equals(seat.commander())) {
            throw new RejectedInputException("deck contents or commander differ from the verified manifest for " + seat.deckId());
        }
        String problem = DeckFormat.Commander.getDeckConformanceProblem(deck);
        if (problem != null) throw new RejectedInputException("Commander legality failed for " + seat.deckId() + ": " + problem);
        return deck;
    }

    private static Map<String, Integer> declaredCards(Path file) throws IOException {
        Map<String, Integer> cards = new LinkedHashMap<>();
        String section = "";
        for (String raw : Files.readAllLines(file)) {
            String line = raw.trim();
            if (line.isEmpty() || line.startsWith("#")) continue;
            if (line.startsWith("[") && line.endsWith("]")) {
                section = line.substring(1, line.length() - 1);
                continue;
            }
            if (section.equalsIgnoreCase("metadata") || section.isEmpty()) continue;
            int space = line.indexOf(' ');
            int pipe = line.indexOf('|');
            if (space <= 0 || pipe <= space) throw new IllegalArgumentException("invalid card row in " + file + ": " + line);
            int count = Integer.parseInt(line.substring(0, space));
            String name = line.substring(space + 1, pipe).trim();
            cards.merge(section + "/" + name, count, Integer::sum);
        }
        return cards;
    }

    private static Map<String, Object> seatReceipt(Seat seat, Deck deck) throws Exception {
        return Map.of("deck_id", seat.deckId(), "file_sha256", sha256(Path.of(seat.deckFile())),
                "commander", deck.getCommanders().get(0).getName(), "total_cards",
                deck.getAllCardsInASinglePool(true, false).countAll());
    }

    private static String sha256(Path path) throws Exception {
        return java.util.HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(path)));
    }

    private static void assertContained(Path root, Path child) {
        if (!child.toAbsolutePath().normalize().startsWith(root.toAbsolutePath().normalize())) {
            throw new IllegalStateException("Forge resolved a writable path outside this game directory: " + child);
        }
    }

    private static void writeJson(Path path, Object value) throws IOException {
        Path temp = path.resolveSibling(path.getFileName() + ".tmp");
        Files.writeString(temp, JSON.toJson(value));
        try { Files.move(temp, path, java.nio.file.StandardCopyOption.ATOMIC_MOVE); }
        catch (java.nio.file.AtomicMoveNotSupportedException ex) {
            Files.move(temp, path, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        }
    }
}
