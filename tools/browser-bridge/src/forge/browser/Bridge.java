package forge.browser;

import com.google.gson.*;
import com.sun.net.httpserver.*;
import forge.GuiDesktop;
import forge.deck.*;
import forge.game.*;
import forge.game.card.CardView;
import forge.game.player.*;
import forge.game.spellability.StackItemView;
import forge.game.zone.ZoneType;
import forge.gamemodes.match.HostedMatch;
import forge.gamemodes.net.*;
import forge.gamemodes.net.event.*;
import forge.gui.GuiBase;
import forge.interfaces.IGameController;
import forge.localinstance.properties.ForgePreferences.FPref;
import forge.model.FModel;
import forge.player.GamePlayerUtil;
import forge.player.LobbyPlayerHuman;
import forge.util.BuildInfo;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.*;
import java.util.concurrent.*;

public final class Bridge {
    static final Gson JSON = new Gson();
    static final int LIMIT = 1_000_000;
    final String origin, token;
    final boolean hosted;
    final HttpServer server;
    volatile MatchSession match;

    Bridge(String origin, int port) throws Exception {
        this(origin, port, "1".equals(System.getenv("FORGE_BRIDGE_HOSTED")), System.getenv("FORGE_BRIDGE_WORKER_TOKEN"));
    }

    Bridge(String origin, int port, boolean hosted, String workerToken) throws Exception {
        this.hosted = hosted;
        URI site = URI.create(origin);
        boolean localHttp = "http".equals(site.getScheme()) && site.getHost() != null && Set.of("localhost", "127.0.0.1", "::1", "[::1]").contains(site.getHost());
        if ((!"https".equals(site.getScheme()) && !localHttp) || site.getHost() == null || site.getUserInfo() != null ||
                site.getQuery() != null || site.getFragment() != null || !(site.getPath().isEmpty() || site.getPath().equals("/")))
            throw new IllegalArgumentException("Origin must be HTTPS, or HTTP on loopback, without a path");
        this.origin = origin.endsWith("/") ? origin.substring(0, origin.length() - 1) : origin;
        byte[] bytes = new byte[32]; new SecureRandom().nextBytes(bytes);
        if (hosted && (workerToken == null || workerToken.length() < 32)) throw new IllegalArgumentException("Missing worker credential");
        token = hosted ? workerToken : Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        server = HttpServer.create(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), port), 0);
        server.createContext("/api/v1/", this::handle);
        server.setExecutor(new ThreadPoolExecutor(2, 8, 30, TimeUnit.SECONDS, new ArrayBlockingQueue<>(64), runnable -> {
            Thread thread = new Thread(runnable, "forge-worker-http"); thread.setDaemon(true); return thread;
        }, new ThreadPoolExecutor.AbortPolicy()));
    }

    void handle(HttpExchange x) throws IOException {
        try {
            String host = x.getRequestHeaders().getFirst("Host");
            String expectedHost = "127.0.0.1:" + server.getAddress().getPort();
            String requestOrigin = x.getRequestHeaders().getFirst("Origin");
            if (!expectedHost.equals(host) || !origin.equals(requestOrigin)) { reply(x, 403, error("Origin or Host rejected")); return; }
            Headers h = x.getResponseHeaders();
            h.set("Access-Control-Allow-Origin", origin); h.set("Vary", "Origin");
            h.set("Access-Control-Allow-Headers", "Authorization, Content-Type");
            h.set("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
            if (!hosted) h.set("Access-Control-Allow-Private-Network", "true");
            h.set("Cache-Control", "no-store");
            if (x.getRequestMethod().equals("OPTIONS")) { x.sendResponseHeaders(204, -1); return; }
            String auth = x.getRequestHeaders().getFirst("Authorization");
            if (auth == null || !MessageDigest.isEqual(("Bearer " + token).getBytes(StandardCharsets.UTF_8), auth.getBytes(StandardCharsets.UTF_8))) {
                reply(x, 401, error("Pairing token rejected")); return;
            }
            int seat = 0;
            if (hosted) {
                String seatHeader = x.getRequestHeaders().getFirst("X-Forge-Seat");
                if (!"0".equals(seatHeader) && !"1".equals(seatHeader)) { reply(x, 403, error("Seat rejected")); return; }
                seat = Integer.parseInt(seatHeader);
            }
            String path = x.getRequestURI().getPath(), method = x.getRequestMethod();
            if (method.equals("POST") && !"application/json".equalsIgnoreCase(x.getRequestHeaders().getFirst("Content-Type"))) {
                reply(x, 415, error("Expected application/json")); return;
            }
            if (method.equals("GET") && path.equals("/api/v1/status")) {
                reply(x, 200, map("schemaVersion", 1, "status", "ready", "engine", "Forge", "engineVersion", BuildInfo.getVersionString()));
            } else if (method.equals("GET") && path.equals("/api/v1/match")) {
                MatchSession current = match;
                if (current != null && current.seat(seat) == null) { reply(x, 403, error("Seat rejected")); return; }
                replyRaw(x, 200, current == null ? JSON.toJson(map("schemaVersion", 1, "status", "idle", "revision", 0, "players", List.of(), "stack", List.of())) : current.seat(seat).snapshot);
            } else if (method.equals("POST") && path.equals("/api/v1/matches")) {
                if (seat != 0) { reply(x, 403, error("Only seat zero creates a match")); return; }
                JsonObject body = body(x);
                synchronized (this) {
                    if (match != null && (hosted || !match.terminal())) { reply(x, 409, error("A match is already active")); return; }
                    match = new MatchSession(body);
                    new Thread(match::start, "forge-bridge-start").start();
                }
                replyRaw(x, 202, match.snapshot);
            } else if (method.equals("POST") && path.equals("/api/v1/action")) {
                MatchSession current = match;
                if (current == null) { reply(x, 409, error("No active match")); return; }
                SeatView viewer = current.seat(seat);
                if (viewer == null) { reply(x, 403, error("Seat rejected")); return; }
                String problem = viewer.submit(body(x));
                reply(x, problem == null ? 202 : 409, problem == null ? map("schemaVersion", 1, "accepted", true) : error(problem));
            } else reply(x, 404, error("Unknown endpoint"));
        } catch (IllegalArgumentException | IllegalStateException e) {
            reply(x, 400, error(e.getMessage() == null ? "Invalid request" : e.getMessage()));
        } catch (Exception e) {
            e.printStackTrace(); reply(x, 500, error("Bridge request failed"));
        } finally { x.close(); }
    }
    static JsonObject body(HttpExchange x) throws IOException {
        byte[] data = x.getRequestBody().readNBytes(LIMIT + 1);
        if (data.length > LIMIT) throw new IllegalArgumentException("Request too large");
        try { return JsonParser.parseString(new String(data, StandardCharsets.UTF_8)).getAsJsonObject(); }
        catch (RuntimeException e) { throw new IllegalArgumentException("Expected a JSON object"); }
    }
    static Map<String,Object> map(Object... pairs) {
        Map<String,Object> m = new LinkedHashMap<>();
        for (int i=0; i<pairs.length; i+=2) m.put((String)pairs[i], pairs[i+1]);
        return m;
    }
    static Map<String,Object> error(String s) { return map("schemaVersion", 1, "error", s); }
    static void reply(HttpExchange x, int status, Object data) throws IOException { replyRaw(x, status, JSON.toJson(data)); }
    static void replyRaw(HttpExchange x, int status, String data) throws IOException {
        byte[] bytes = data.getBytes(StandardCharsets.UTF_8);
        x.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        x.sendResponseHeaders(status, bytes.length); x.getResponseBody().write(bytes);
    }
    static String string(JsonObject o, String key) {
        if (!o.has(key) || !o.get(key).isJsonPrimitive() || !o.get(key).getAsJsonPrimitive().isString()) throw new IllegalArgumentException("Missing " + key);
        return o.get(key).getAsString();
    }
    static Deck deck(JsonObject json) {
        Deck deck = new Deck(string(json, "name"));
        if (!json.has("entries") || !json.get("entries").isJsonArray()) throw new IllegalArgumentException("Deck needs entries");
        if (json.getAsJsonArray("entries").size() > 300) throw new IllegalArgumentException("Too many deck entries");
        for (JsonElement element : json.getAsJsonArray("entries")) {
            JsonObject entry = element.getAsJsonObject();
            String name = string(entry, "name"), section = string(entry, "section");
            int quantity = entry.get("quantity").getAsInt();
            if (quantity < 1 || quantity > 100) throw new IllegalArgumentException("Invalid quantity for " + name);
            var card = FModel.getMagicDb().getCommonCards().getCard(name);
            if (card == null) throw new IllegalArgumentException("Unknown card: " + name);
            DeckSection s = switch (section) { case "main" -> DeckSection.Main; case "commander" -> DeckSection.Commander; default -> throw new IllegalArgumentException("Unknown deck section"); };
            deck.getOrCreate(s).add(card, quantity);
        }
        String issue = DeckFormat.Commander.getDeckConformanceProblem(deck);
        if (issue != null) throw new IllegalArgumentException(deck.getName() + ": " + issue);
        return deck;
    }
    static final class InlineGui extends GuiDesktop {
        @Override public String getAssetsDir() {
            return System.getProperty("forge.player.assets", super.getAssetsDir());
        }
        @Override public void invokeInEdtNow(Runnable r) { r.run(); }
        @Override public void invokeInEdtLater(Runnable r) { r.run(); }
        @Override public void invokeInEdtAndWait(Runnable r) { r.run(); }
        @Override public boolean isGuiThread() { return false; }
    }
    record AllocationTarget(String id, Object entity, String label, int min, int max, int lethal, boolean defender) {
        AllocationTarget(Object entity, String label, int min, int max, int lethal, boolean defender) {
            this(UUID.randomUUID().toString(), entity, label, min, max, lethal, defender);
        }
        Map<String,Object> view() {
            return map("id", id, "label", label, "min", min, "max", max, "lethal", lethal, "defender", defender);
        }
    }
    record Allocation(String kind, int total, String amountLabel, List<AllocationTarget> targets,
                      boolean ordered, boolean divideFreely, boolean maySkip) {
        Map<Object,Integer> decode(JsonObject action) {
            if (!action.has("allocations") || !action.get("allocations").isJsonArray())
                throw new IllegalArgumentException("Assign an amount to every target");
            JsonArray entries = action.getAsJsonArray("allocations");
            if (entries.size() != targets.size()) throw new IllegalArgumentException("Assign an amount to every target");
            Map<String,Integer> amounts = new HashMap<>();
            for (JsonElement entry : entries) {
                if (!entry.isJsonObject()) throw new IllegalArgumentException("Invalid allocation");
                JsonObject value = entry.getAsJsonObject();
                String id = string(value, "id");
                JsonElement amount = value.get("amount");
                if (amount == null || !amount.isJsonPrimitive() || !amount.getAsJsonPrimitive().isNumber())
                    throw new IllegalArgumentException("Amounts must be whole numbers");
                int number;
                try { number = amount.getAsBigDecimal().intValueExact(); }
                catch (ArithmeticException | NumberFormatException e) { throw new IllegalArgumentException("Amounts must be whole numbers within range"); }
                if (amounts.putIfAbsent(id, number) != null) throw new IllegalArgumentException("Duplicate allocation target");
            }
            Map<Object,Integer> result = new LinkedHashMap<>();
            long assigned = 0;
            boolean earlierBelowLethal = false;
            for (AllocationTarget target : targets) {
                Integer amount = amounts.get(target.id());
                if (amount == null) throw new IllegalArgumentException("Unknown or missing allocation target");
                if (amount < target.min() || amount > target.max()) throw new IllegalArgumentException("Amount outside the allowed range for " + target.label());
                if (kind.equals("combat") && !divideFreely && earlierBelowLethal && amount > 0 && (ordered || target.defender()))
                    throw new IllegalArgumentException(target.defender() ? "Assign lethal damage to every blocker before the defender" : "Assign lethal damage to earlier blockers first");
                if (!target.defender()) earlierBelowLethal |= amount < target.lethal();
                assigned += amount;
                result.put(target.entity(), amount);
            }
            if (assigned != total) throw new IllegalArgumentException("Assign exactly " + total + " " + amountLabel);
            return result;
        }
    }
    record InputOption(String id, String value) {
        Map<String,Object> view() { return map("id", id, "label", value); }
    }
    record TextInput(String title, String initial, List<InputOption> options, boolean numeric) {
        Map<String,Object> view() {
            return map("title", title, "initial", initial, "numeric", numeric,
                    "options", options == null ? null : options.stream().map(InputOption::view).toList());
        }
        String decode(JsonObject action) {
            String kind = string(action, "kind");
            if (kind.equals("cancel")) return null;
            if (!kind.equals("input")) throw new IllegalArgumentException("Action does not match the input prompt");
            if (options == null) return string(action, "value");
            String id = string(action, "optionId");
            return options.stream().filter(option -> option.id().equals(id)).findFirst()
                    .orElseThrow(() -> new IllegalArgumentException("Unknown input option")).value();
        }
    }
    record ManipulationCard(String id, CardView card, String label, boolean movable) {
        Map<String,Object> view() { return map("id", id, "label", label, "movable", movable); }
    }
    record CardManipulation(List<ManipulationCard> cards, boolean toTop, boolean toBottom, boolean toAnywhere) {
        Map<String,Object> view() {
            return map("cards", cards.stream().map(ManipulationCard::view).toList(),
                    "toTop", toTop, "toBottom", toBottom, "toAnywhere", toAnywhere);
        }
        List<CardView> decode(JsonObject action) {
            if (!string(action, "kind").equals("manipulate"))
                throw new IllegalArgumentException("Action does not match the card order prompt");
            if (!action.has("cardIds") || !action.get("cardIds").isJsonArray()
                    || action.getAsJsonArray("cardIds").size() != cards.size())
                throw new IllegalArgumentException("Return every card exactly once");
            Map<String,ManipulationCard> originals = new HashMap<>();
            for (ManipulationCard card : cards) originals.put(card.id(), card);
            List<ManipulationCard> ordered = new ArrayList<>();
            for (JsonElement entry : action.getAsJsonArray("cardIds")) {
                if (!entry.isJsonPrimitive() || !entry.getAsJsonPrimitive().isString())
                    throw new IllegalArgumentException("Card IDs must be strings");
                ManipulationCard card = originals.remove(entry.getAsString());
                if (card == null) throw new IllegalArgumentException("Unknown or duplicate card");
                ordered.add(card);
            }
            if (!permits(ordered)) throw new IllegalArgumentException("That card order is not allowed");
            return ordered.stream().map(ManipulationCard::card).toList();
        }
        boolean permits(List<ManipulationCard> ordered) {
            if (toAnywhere) return ordered.stream().filter(card -> !card.movable()).toList()
                    .equals(cards.stream().filter(card -> !card.movable()).toList());
            int start = 0, end = ordered.size();
            if (toTop) while (start < end && ordered.get(start).movable()) start++;
            if (toBottom) while (end > start && ordered.get(end - 1).movable()) end--;
            Set<String> moved = new HashSet<>();
            for (int i = 0; i < start; i++) moved.add(ordered.get(i).id());
            for (int i = end; i < ordered.size(); i++) moved.add(ordered.get(i).id());
            return ordered.subList(start, end).equals(cards.stream().filter(card -> !moved.contains(card.id())).toList());
        }
    }
    record ParticipantResult(String name, String outcome, String lossReason) { }
    record CompletionResult(String kind, String endReason, int turns, List<ParticipantResult> participants) {
        static CompletionResult from(GameOutcome outcome) {
            if (outcome == null || outcome.getWinCondition() == null || outcome.getPlayerNames().isEmpty()) return null;
            List<ParticipantResult> participants = new ArrayList<>();
            for (var entry : outcome) {
                String name = outcome.getPlayerNames().get(entry.getKey());
                var stats = entry.getValue();
                if (name == null || stats == null || stats.getOutcome() == null) return null;
                var player = stats.getOutcome();
                String state = player.hasWon() ? "won" : player.lossState == GameLossReason.IntentionalDraw ? "draw" : "lost";
                participants.add(new ParticipantResult(name, state, player.lossState == null ? null : player.lossState.name()));
            }
            if (participants.size() != outcome.getPlayerNames().size()) return null;
            participants.sort(Comparator.comparing((ParticipantResult participant) -> !participant.name().equals("You"))
                    .thenComparing(ParticipantResult::name));
            return new CompletionResult(outcome.isDraw() ? "draw" : "decided", outcome.getWinCondition().name(),
                    outcome.getLastTurnNumber(), List.copyOf(participants));
        }
    }
    static final class MatchSession extends SeatView {
        final List<SeatView> seats;
        final BlockingQueue<SeatView> concessions = new LinkedBlockingQueue<>(2);
        MatchSession(JsonObject request) {
            super(request, null, 0);
            String mode = request.has("mode") ? string(request, "mode") : "cpu";
            if (!Set.of("cpu", "human").contains(mode)) throw new IllegalArgumentException("Unknown mode");
            seats = mode.equals("human") ? List.of(this, new SeatView(request, this, 1)) : List.of(this);
        }
        SeatView seat(int number) { return number >= 0 && number < seats.size() ? seats.get(number) : null; }
    }
    static class SeatView implements IRemote {
        final String id;
        final MatchSession owner;
        final int seatNumber;
        final JsonObject request;
        final BlockingQueue<JsonObject> commands = new LinkedBlockingQueue<>(8);
        final Map<String,CardView> cards = new HashMap<>();
        final Map<String,PlayerView> players = new HashMap<>();
        final Map<String,Object> choices = new LinkedHashMap<>();
        volatile String snapshot;
        volatile String status = "starting";
        static boolean initialized;
        String error, message = "", promptId, promptKind;
        Map<String,Object> prompt;
        Allocation allocation;
        TextInput input;
        CardManipulation manipulation;
        CompletionResult result;
        PlayerView human;
        PumpGui gui;
        long revision;
        boolean inFlight;
        boolean priorityActive;
        SeatView(JsonObject request, MatchSession owner, int seatNumber) {
            this.request = request; this.owner = owner; this.seatNumber = seatNumber;
            this.id = owner == null ? UUID.randomUUID().toString() : owner.id;
            publish();
        }
        MatchSession matchOwner() { return owner == null ? (MatchSession)this : owner; }
        synchronized boolean terminal() { return status.equals("finished") || status.equals("error"); }
        synchronized String submit(JsonObject action) {
            if (terminal()) return "Match is over";
            if (!id.equals(string(action, "matchId"))) return "Stale match";
            Long actionRevision = null;
            if (action.has("revision")) {
                JsonElement value = action.get("revision");
                if (!value.isJsonPrimitive() || !value.getAsJsonPrimitive().isNumber())
                    return "Revision must be a whole number within range";
                try { actionRevision = value.getAsBigDecimal().longValueExact(); }
                catch (ArithmeticException | NumberFormatException e) { return "Revision must be a whole number within range"; }
            }
            String kind = string(action, "kind");
            if (kind.equals("concede")) {
                if (actionRevision != null && actionRevision != revision) return "Stale revision";
                if (action.has("promptId") && !Objects.equals(promptId, string(action, "promptId"))) return "Stale prompt";
                if (inFlight) return "An action is already in flight";
                if (gui == null || human == null) {
                    if (!commands.offer(action.deepCopy())) return "An action is already in flight";
                    inFlight = true; return null;
                }
                if (!matchOwner().concessions.offer(this)) return "An action is already in flight";
                inFlight = true;
                return null;
            }
            if (actionRevision == null || actionRevision != revision) return "Stale revision";
            if (promptId == null || !promptId.equals(string(action, "promptId"))) return "Stale prompt";
            if ("priority".equals(promptKind) && !priorityActive) return "Stale prompt";
            if (inFlight) return "An action is already in flight";
            if (promptKind.equals("input") || promptKind.equals("manipulate")) {
                try {
                    if (promptKind.equals("input")) input.decode(action);
                    else manipulation.decode(action);
                } catch (IllegalArgumentException e) { return e.getMessage(); }
                inFlight = true; commands.offer(action.deepCopy()); return null;
            }
            if (promptKind.equals("allocation")) {
                if (kind.equals("skip")) {
                    if (!allocation.maySkip()) return "This assignment cannot be skipped";
                } else if (kind.equals("allocation")) {
                    try { allocation.decode(action); }
                    catch (IllegalArgumentException e) { return e.getMessage(); }
                } else return "Action does not match the prompt";
                inFlight = true; commands.offer(action.deepCopy()); return null;
            }
            if (!Set.of("ok", "cancel", "card", "player", "choice", "number", "concede").contains(kind)) return "Unknown action";
            if (!kind.equals("concede")) {
                if (promptKind.equals("priority") && !Set.of("ok", "cancel", "card", "player").contains(kind)) return "Action does not match the prompt";
                if (promptKind.equals("confirm") && !Set.of("ok", "cancel").contains(kind)) return "Action does not match the prompt";
                if (promptKind.equals("reveal") && !kind.equals("ok")) return "Action does not match the prompt";
                if ((promptKind.equals("choices") || promptKind.equals("order")) && !kind.equals("choice")) return "Action does not match the prompt";
                if (kind.equals("choice")) {
                    if (!action.has("choiceIds") || !action.get("choiceIds").isJsonArray()) return "Choices are required";
                    JsonArray ids = action.getAsJsonArray("choiceIds");
                    if (ids.size() < (int)prompt.get("min") || ids.size() > (int)prompt.get("max")) return "Wrong number of choices";
                    Set<String> unique = new HashSet<>();
                    for (JsonElement v : ids) {
                        if (!v.isJsonPrimitive() || !v.getAsJsonPrimitive().isString() || !choices.containsKey(v.getAsString()) || !unique.add(v.getAsString())) return "Invalid choice";
                    }
                }
            }
            if (kind.equals("card") && !cards.containsKey(string(action, "cardId"))) return "Unknown card";
            if (kind.equals("player") && !players.containsKey(string(action, "playerId"))) return "Unknown player";
            inFlight = true; commands.offer(action.deepCopy()); return null;
        }
        void start() {
            try {
                synchronized (MatchSession.class) {
                    if (!initialized) {
                        GuiBase.setInterface(new InlineGui());
                        GuiBase.setUsingAppDirectory(true);
                        FModel.initialize(null, p -> { p.setPref(FPref.LOAD_CARD_SCRIPTS_LAZILY, false); p.setPref(FPref.UI_LANGUAGE, "en-US"); p.setPref(FPref.PLAYER_NAME, "You"); p.setPref(FPref.UI_ENABLE_MUSIC, false); p.setPref(FPref.UI_ENABLE_SOUNDS, false); return null; });
                        initialized = true;
                    }
                }
                FModel.getPreferences().setPref(FPref.UI_RECORD_REPLAYS, false);
                FModel.getPreferences().setPref(FPref.UI_SHOW_ACTIONABLE_HIGHLIGHTS, false);
                Deck h = deck(request.getAsJsonObject("humanDeck")), a = deck(request.getAsJsonObject("aiDeck"));
                RegisteredPlayer hp = RegisteredPlayer.forCommander(h).setPlayer(new LobbyPlayerHuman("You"));
                RegisteredPlayer ap = RegisteredPlayer.forCommander(a).setPlayer(matchOwner().seats.size() == 2
                        ? new LobbyPlayerHuman("Friend") : GamePlayerUtil.createAiPlayer("CPU"));
                gui = new PumpGui(this);
                GameRules rules = new GameRules(GameType.Commander);
                rules.setGamesPerMatch(1);
                rules.setWarnAboutAICards(false);
                Map<RegisteredPlayer, forge.gui.interfaces.IGuiGame> guis = new LinkedHashMap<>();
                guis.put(hp, gui);
                if (matchOwner().seats.size() == 2) {
                    SeatView guest = matchOwner().seat(1);
                    guest.gui = new PumpGui(guest); guis.put(ap, guest.gui);
                }
                new HostedMatch().startMatch(rules, Set.of(GameType.Commander), List.of(hp, ap), guis, null);
            } catch (Throwable t) { fail(t); }
        }
        void fail(Throwable t) {
            for (SeatView seat : matchOwner().seats) synchronized (seat) {
                seat.status = "error";
                seat.error = t.getMessage() == null ? t.getClass().getSimpleName() : t.getMessage();
                seat.publish();
            }
            t.printStackTrace();
        }
        synchronized void publish() {
            revision++;
            Map<String,Object> out = map("schemaVersion", 1, "matchId", id, "seat", seatNumber, "revision", revision, "status", status,
                    "turn", 0, "phase", "", "activePlayerId", null, "viewerPlayerId", human == null ? null : pid(human), "players", List.of(), "stack", List.of());
            if (error != null) out.put("error", error);
            GameView view = gui == null ? null : gui.getGameView();
            if (view != null) {
                out.put("turn", view.getTurn()); out.put("phase", String.valueOf(view.getPhase()));
                if (view.getPlayerTurn() != null) out.put("activePlayerId", pid(view.getPlayerTurn()));
                cards.clear(); players.clear();
                List<Object> ps = new ArrayList<>();
                if (view.getPlayers() != null) for (PlayerView p : view.getPlayers()) {
                    players.put(pid(p), p);
                    Map<String,Object> player = map("id", pid(p), "name", p.getName(), "life", p.getLife(),
                            "handCount", p.getZoneSize(ZoneType.Hand), "libraryCount", p.getZoneSize(ZoneType.Library),
                            "battlefield", zone(p.getBattlefield()), "graveyard", zone(p.getGraveyard()),
                            "exile", zone(p.getExile()), "command", zone(p.getCommand()));
                    if (p.equals(human)) player.put("hand", zone(p.getHand()));
                    ps.add(player);
                }
                out.put("players", ps);
                List<Object> stack = new ArrayList<>();
                if (view.getStack() != null) for (StackItemView item : view.getStack()) stack.add(map("id", String.valueOf(item.getId()), "label", item.toString()));
                out.put("stack", stack);
                if (view.isGameOver()) {
                    if (!status.equals("error")) status = "finished";
                    if (result == null) result = CompletionResult.from(view.getOutcome());
                }
            }
            if (terminal()) {
                prompt = null; promptId = null; promptKind = null; choices.clear();
                allocation = null; input = null; manipulation = null; inFlight = false;
            }
            out.put("status", status);
            if (result != null) out.put("result", result);
            if (prompt != null && (!"priority".equals(promptKind) || priorityActive)) out.put("prompt", prompt);
            snapshot = JSON.toJson(out);
        }
        String pid(PlayerView p) { return String.valueOf(p.getId()); }
        List<Object> zone(Iterable<CardView> source) {
            List<Object> result = new ArrayList<>();
            for (CardView c : source) {
                String cid = String.valueOf(c.getId()); cards.put(cid, c);
                if (!c.canBeShownTo(human)) { result.add(map("id", cid, "name", "Face-down card", "tapped", c.isTapped())); continue; }
                var state = c.getCurrentState();
                result.add(map("id", cid, "name", c.getName(), "mana", String.valueOf(state.getManaCost()),
                        "type", String.valueOf(state.getType()), "text", c.getText(), "tapped", c.isTapped()));
            }
            return result;
        }
        synchronized void newPrompt(String kind, String text) {
            promptId = UUID.randomUUID().toString(); promptKind = kind;
            allocation = null; input = null; manipulation = null;
            prompt = map("id", promptId, "kind", kind, "message", text); inFlight = false;
        }
        @Override public void send(NetEvent event) {
            if (!(event instanceof GuiGameEvent)) return;
            GuiGameEvent e = (GuiGameEvent) event; Object[] a = e.getObjects();
            synchronized (this) {
                switch (e.getMethod()) {
                    case openView -> {
                        var ps = (Iterable<PlayerView>) a[0]; human = ps.iterator().next(); status = "playing";
                        if (!commands.isEmpty() && "concede".equals(string(commands.peek(), "kind"))) {
                            commands.poll(); matchOwner().concessions.offer(this);
                        }
                    }
                    case showPromptMessage -> { message = String.valueOf(a[1]); if (prompt != null && "priority".equals(promptKind)) prompt.put("message", message); }
                    case updateButtons -> {
                        if (human != null && human.equals(a[0])) {
                            newPrompt("priority", message);
                            prompt.put("buttons", List.of(map("id", "ok", "label", a[1], "enabled", a[3]), map("id", "cancel", "label", a[2], "enabled", a[4])));
                        }
                    }
                    case afterGameEnd, finishGame -> { if (!status.equals("error")) status = "finished"; }
                    default -> { }
                }
                publish();
            }
        }
        @Override public Object sendAndWait(IdentifiableNetEvent event) {
            GuiGameEvent e = (GuiGameEvent) event; Object[] a = e.getObjects();
            try {
                synchronized (this) {
                    choices.clear();
                    switch (e.getMethod()) {
                        case getAbilityToPlay -> choicePrompt("Choose an ability", (List<?>)a[1], 1, 1);
                        case getChoices -> {
                            if ((int)a[1] == -1 && (int)a[2] == -1) revealPrompt(String.valueOf(a[0]), (List<?>)a[3]);
                            else choicePrompt(String.valueOf(a[0]), (List<?>)a[3], (int)a[1], (int)a[2]);
                        }
                        case order -> {
                            List<Object> all = new ArrayList<>((List<?>)a[4]);
                            if (a[5] != null) all.addAll((List<?>)a[5]);
                            int remainingMin = (int)a[2], remainingMax = (int)a[3];
                            int min = remainingMax < 0 ? 0 : Math.max(0, all.size() - remainingMax);
                            int max = remainingMax < 0 ? all.size() : all.size() - remainingMin;
                            choicePrompt(String.valueOf(a[0]) + " — " + String.valueOf(a[1]), all, min, max);
                            promptKind = "order"; prompt.put("kind", "order");
                        }
                        case chooseSingleEntityForEffect -> choicePrompt(String.valueOf(a[0]), (List<?>)a[1], (boolean)a[3] ? 0 : 1, 1);
                        case chooseEntitiesForEffect -> choicePrompt(String.valueOf(a[0]), (List<?>)a[1], (int)a[2], (int)a[3]);
                        case confirm -> { newPrompt("confirm", String.valueOf(a[1])); prompt.put("buttons", buttons()); }
                        case showConfirmDialog -> { newPrompt("confirm", String.valueOf(a[0])); prompt.put("buttons", buttons()); }
                        case showOptionDialog -> choicePrompt(String.valueOf(a[0]), (List<?>)a[3], 1, 1);
                        case assignCombatDamage -> combatPrompt((CardView)a[0], (List<CardView>)a[1], (int)a[2], (GameEntityView)a[3], (boolean)a[4], (boolean)a[5]);
                        case assignGenericAmount -> genericPrompt((CardView)a[0], (Map<Object,Integer>)a[1], (int)a[2], (boolean)a[3], String.valueOf(a[4]));
                        case showInputDialog -> inputPrompt(String.valueOf(a[0]), String.valueOf(a[1]),
                                (String)a[3], (List<String>)a[4], (boolean)a[5]);
                        case manipulateCardList -> manipulationPrompt(String.valueOf(a[0]), (Iterable<CardView>)a[1],
                                (Iterable<CardView>)a[2], (boolean)a[3], (boolean)a[4], (boolean)a[5]);
                        default -> { newPrompt("unsupported", "This decision is not supported by the bridge: " + e.getMethod()); status = "error"; error = String.valueOf(prompt.get("message")); publish(); throw new IllegalStateException(error); }
                    }
                    publish();
                }
                while (true) {
                    JsonObject action = nextCommand(null);
                    synchronized (this) {
                        String kind = string(action, "kind");
                        if (kind.equals("concede")) { gui.getGameController(human).concede(); status = "finished"; prompt = null; promptId = null; input = null; manipulation = null; publish(); throw new CancellationException("Player conceded"); }
                        if (!Objects.equals(promptId, string(action, "promptId"))) continue;
                        if (promptKind.equals("input") || promptKind.equals("manipulate")) {
                            Object result = promptKind.equals("input") ? input.decode(action) : manipulation.decode(action);
                            prompt = null; promptId = null; input = null; manipulation = null; inFlight = false; publish();
                            return result;
                        }
                        if (promptKind.equals("allocation")) {
                            Map<Object,Integer> result = kind.equals("skip") ? null : allocation.decode(action);
                            prompt = null; promptId = null; allocation = null; inFlight = false; publish();
                            return result;
                        }
                        if (promptKind.equals("reveal") && kind.equals("ok")) {
                            prompt = null; promptId = null; inFlight = false; publish();
                            return List.of();
                        }
                        if (promptKind.equals("confirm") && (kind.equals("ok") || kind.equals("cancel"))) { prompt = null; promptId = null; inFlight = false; publish(); return kind.equals("ok"); }
                        if ((promptKind.equals("choices") || promptKind.equals("order")) && kind.equals("choice")) {
                            List<Object> selected = new ArrayList<>();
                            JsonArray ids = action.has("choiceIds") && action.get("choiceIds").isJsonArray() ? action.getAsJsonArray("choiceIds") : new JsonArray();
                            Set<String> unique = new HashSet<>();
                            for (JsonElement v : ids) { String k = v.getAsString(); if (!choices.containsKey(k) || !unique.add(k)) { selected.clear(); break; } selected.add(choices.get(k)); }
                            int min = (int)prompt.get("min"), max = (int)prompt.get("max");
                            if (selected.size() >= min && selected.size() <= max) {
                                prompt = null; promptId = null; inFlight = false; publish();
                                return switch (e.getMethod()) {
                                    case getAbilityToPlay, chooseSingleEntityForEffect -> selected.isEmpty() ? null : selected.get(0);
                                    case showOptionDialog -> selected.isEmpty() ? -1 : ((List<?>)a[3]).indexOf(selected.get(0));
                                    case order -> new forge.gui.interfaces.IGuiGame.OrderResult<>(selected, false);
                                    default -> selected;
                                };
                            }
                        }
                        inFlight = false; publish();
                    }
                }
            } catch (InterruptedException ex) { Thread.currentThread().interrupt(); throw new IllegalStateException("Bridge interrupted", ex); }
        }
        List<Object> buttons() { return List.of(map("id", "ok", "label", "Yes", "enabled", true), map("id", "cancel", "label", "No", "enabled", true)); }
        void inputPrompt(String message, String title, String initial, List<String> options, boolean numeric) {
            newPrompt("input", message);
            input = new TextInput(title, initial == null ? "" : initial, options == null ? null : options.stream()
                    .map(value -> new InputOption(UUID.randomUUID().toString(), value)).toList(), numeric);
            prompt.putAll(input.view());
        }
        void manipulationPrompt(String title, Iterable<CardView> originals, Iterable<CardView> movable,
                                boolean top, boolean bottom, boolean anywhere) {
            newPrompt("manipulate", title);
            Set<CardView> movableCards = new HashSet<>();
            for (CardView card : movable) movableCards.add(card);
            List<ManipulationCard> entries = new ArrayList<>();
            for (CardView card : originals) entries.add(new ManipulationCard(UUID.randomUUID().toString(), card,
                    allocationLabel(card), movableCards.contains(card)));
            manipulation = new CardManipulation(List.copyOf(entries), top, bottom, anywhere);
            prompt.putAll(manipulation.view());
        }
        String allocationLabel(Object entity) {
            if (entity instanceof CardView card) return card.canBeShownTo(human) ? card.getName() : "Face-down card";
            return String.valueOf(entity);
        }
        void allocationPrompt(String message, Allocation value) {
            newPrompt("allocation", message); allocation = value;
            prompt.putAll(map("allocationKind", value.kind(), "total", value.total(), "amountLabel", value.amountLabel(),
                    "ordered", value.ordered(), "divideFreely", value.divideFreely(), "maySkip", value.maySkip(),
                    "targets", value.targets().stream().map(AllocationTarget::view).toList()));
        }
        void combatPrompt(CardView source, List<CardView> blockers, int damage, GameEntityView defender, boolean overrideOrder, boolean maySkip) {
            var state = source.getCurrentState();
            boolean freely = state.hasDivideDamage() && overrideOrder;
            List<AllocationTarget> targets = new ArrayList<>();
            for (CardView blocker : blockers) {
                int lethal = Math.max(0, blocker.getLethalDamage());
                if (blocker.getCurrentState().isPlaneswalker()) lethal = Math.max(0, Integer.parseInt(blocker.getCurrentState().getLoyalty()));
                else if (state.hasDeathtouch()) lethal = Math.min(lethal, 1);
                targets.add(new AllocationTarget(blocker, allocationLabel(blocker), 0, damage, lethal, false));
            }
            if (defender != null && (state.hasTrample() || freely))
                targets.add(new AllocationTarget(null, allocationLabel(defender), 0, damage, 0, true));
            allocationPrompt("Assign combat damage from " + allocationLabel(source),
                    new Allocation("combat", damage, "damage", List.copyOf(targets), !overrideOrder, freely, maySkip));
        }
        void genericPrompt(CardView source, Map<Object,Integer> affected, int amount, boolean atLeastOne, String label) {
            List<AllocationTarget> targets = new ArrayList<>();
            for (var target : affected.entrySet()) targets.add(new AllocationTarget(target.getKey(), allocationLabel(target.getKey()),
                    atLeastOne ? 1 : 0, target.getValue() == null ? amount : target.getValue(), 0, false));
            allocationPrompt("Assign " + label + (source == null ? "" : " from " + allocationLabel(source)),
                    new Allocation("generic", amount, label, List.copyOf(targets), false, false, false));
        }
        void revealPrompt(String text, List<?> options) {
            newPrompt("reveal", text);
            prompt.put("items", options.stream().map(this::allocationLabel).toList());
            prompt.put("buttons", List.of(map("id", "ok", "label", "Continue", "enabled", true)));
        }
        void choicePrompt(String text, List<?> options, int min, int max) {
            newPrompt("choices", text); List<Object> list = new ArrayList<>();
            for (Object option : options) { String key = UUID.randomUUID().toString(); choices.put(key, option); String label = option instanceof CardView && !((CardView)option).canBeShownTo(human) ? "Face-down card" : String.valueOf(option); list.add(map("id", key, "label", label)); }
            prompt.put("min", min); prompt.put("max", max); prompt.put("choices", list);
        }
        JsonObject nextCommand(CountDownLatch done) throws InterruptedException {
            while (done == null || done.getCount() > 0) {
                SeatView conceding = matchOwner().concessions.poll();
                if (conceding != null) {
                    conceding.gui.getGameController(conceding.human).concede();
                    for (SeatView seat : matchOwner().seats) synchronized (seat) {
                        seat.status = "finished"; seat.publish();
                    }
                    if (done != null) return null;
                    throw new CancellationException("Player conceded");
                }
                JsonObject command = commands.poll(50, TimeUnit.MILLISECONDS);
                if (command != null) return command;
            }
            return null;
        }
        void pump(CountDownLatch done) {
            synchronized (this) { priorityActive = true; publish(); }
            try {
                while (done.getCount() > 0) {
                    JsonObject action = nextCommand(done);
                    if (action == null) return;
                    String kind = string(action, "kind");
                    String answeredPrompt = kind.equals("concede") ? null : string(action, "promptId");
                    IGameController controller = gui.getGameController(human);
                    switch (kind) {
                        case "ok" -> controller.selectButtonOk();
                        case "cancel" -> controller.selectButtonCancel();
                        case "card" -> controller.selectCard(cards.get(string(action, "cardId")), null, null);
                        case "player" -> controller.selectPlayer(players.get(string(action, "playerId")), null);
                        case "concede" -> controller.concede();
                        default -> { }
                    }
                    synchronized (this) {
                        if (Objects.equals(answeredPrompt, promptId) && inFlight) { inFlight = false; publish(); }
                    }
                }
            } catch (CancellationException e) { throw e; }
            catch (Throwable t) { fail(t); throw new IllegalStateException(t); }
            finally {
                synchronized (this) {
                    priorityActive = false;
                    if ("priority".equals(promptKind)) { prompt = null; promptId = null; }
                    publish();
                }
            }
        }
    }
    static final class PumpGui extends ProtocolGuiGame {
        final SeatView match;
        PumpGui(SeatView match) { super(match); this.match = match; }
        @Override public void awaitInput(CountDownLatch done) { match.pump(done); }
    }
    public static void main(String[] args) throws Exception {
        if (args.length < 1 || args.length > 2) throw new IllegalArgumentException("Usage: Bridge https://your-site-origin");
        Bridge bridge = new Bridge(args[0], args.length == 2 ? Integer.parseInt(args[1]) : 8787); bridge.server.start();
        System.out.println((bridge.hosted ? "Forge worker" : "Forge bridge") + " listening at http://127.0.0.1:" + bridge.server.getAddress().getPort());
        if (!bridge.hosted) System.out.println("Pairing token: " + bridge.token);
    }
}
