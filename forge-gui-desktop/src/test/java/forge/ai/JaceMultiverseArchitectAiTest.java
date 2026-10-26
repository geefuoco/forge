package forge.ai;

import forge.game.Game;
import forge.game.ability.ApiType;
import forge.game.card.Card;
import forge.game.card.CounterEnumType;
import forge.game.player.Player;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;
import org.testng.Assert;
import org.testng.annotations.Test;

public class JaceMultiverseArchitectAiTest extends AITest {
    @Test
    public void convertsDisposableToken() {
        Game game = initAndCreateGame();
        Player ai = game.getPlayers().get(1);
        moveToMain2(game, ai);
        SpellAbility ability = addJaceAbility(ai);
        Card token = addToken("w_1_1_soldier", ai);
        addCardToZone("Archon of Cruelty", ai, ZoneType.Library);
        for (int i = 0; i < 8; i++) {
            addCardToZone("Island", ai, ZoneType.Library);
        }

        Assert.assertTrue(ability.canTarget(token));
        Assert.assertTrue(ComputerUtilCost.canPayCost(ability, ai, false));
        Assert.assertEquals(SpellApiToAi.Converter.get(ability).canPlayWithSubs(ai, ability).decision(),
                AiPlayDecision.WillPlay);
        Assert.assertEquals(ability.getTargets().getTargetCards().size(), 1);
        Assert.assertSame(ability.getTargets().getTargetCards().get(0), token);
        Assert.assertEquals(((PlayerControllerAi) ai.getController()).getAi().canPlaySa(ability),
                AiPlayDecision.WillPlay);
    }

    @Test
    public void keepsValuableCreature() {
        Game game = initAndCreateGame();
        Player ai = game.getPlayers().get(1);
        moveToMain2(game, ai);
        SpellAbility ability = addJaceAbility(ai);
        Card archon = addCard("Archon of Cruelty", ai);
        addCardToZone("Island", ai, ZoneType.Library);

        Assert.assertTrue(ability.canTarget(archon));
        Assert.assertFalse(SpellApiToAi.Converter.get(ability).canPlayWithSubs(ai, ability).willingToPlay());
    }

    private SpellAbility addJaceAbility(Player ai) {
        Card jace = addCard("Jace, Multiverse Architect", ai);
        jace.setCounters(CounterEnumType.LOYALTY, 4);
        SpellAbility ability = jace.getSpellAbilities().stream()
                .filter(sa -> sa.isAbility() && sa.getApi() == ApiType.ChangeZone)
                .findFirst().orElseThrow();
        ability.setActivatingPlayer(ai);
        return ability;
    }
}
