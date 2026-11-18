package com.dr1ft.DiscordBot.Commands;

import net.dv8tion.jda.api.events.guild.GuildJoinEvent;
import net.dv8tion.jda.api.events.guild.GuildReadyEvent;
import net.dv8tion.jda.api.events.interaction.command.SlashCommandInteractionEvent;
import net.dv8tion.jda.api.hooks.ListenerAdapter;
import net.dv8tion.jda.api.interactions.commands.OptionType;
import net.dv8tion.jda.api.interactions.commands.build.CommandData;
import net.dv8tion.jda.api.interactions.commands.build.Commands;

import java.util.ArrayList;
import java.util.List;

public class CommandManager extends ListenerAdapter {

    @Override
    public void onSlashCommandInteraction(SlashCommandInteractionEvent event) {
        String command = event.getName();
        if (command.equals("ping")) {
            event.reply("pong").queue();
        }
    }

    @Override
    public void onGuildReady(GuildReadyEvent event) {
        List<CommandData> commandData = new ArrayList<>();
        commandData.add(Commands.slash("ping", "Risponde con pong!"));
        commandData.add(Commands.slash("stop", "Ferma la riproduzione"));
        commandData.add(Commands.slash("skip", "Salta alla prossima Traccia"));
        commandData.add(Commands.slash("pause", "mette in pausa la traccia"));
        commandData.add(Commands.slash("resume", "Riprende la riproduzione"));
        commandData.add(Commands.slash("play", "Riproduce la canzone").addOption(OptionType.STRING, "url", "the url or name of the song"));
        commandData.add(Commands.slash("setvolume", "imposta il volume del bot").addOption(OptionType.INTEGER, "volume", "il valore del volume"));
        event.getGuild().updateCommands().addCommands(commandData).queue();
    }

    @Override
    public void onGuildJoin(GuildJoinEvent event) {
        List<CommandData> commandData = new ArrayList<>();
        commandData.add(Commands.slash("ping", "Risponde con pong!"));
        commandData.add(Commands.slash("stop", "Ferma la riproduzione"));
        commandData.add(Commands.slash("skip", "Salta alla prossima Traccia"));
        commandData.add(Commands.slash("pause", "mette in pausa la traccia"));
        commandData.add(Commands.slash("resume", "Riprende la riproduzione"));
        commandData.add(Commands.slash("play", "Riproduce la canzone").addOption(OptionType.STRING, "url", "the url or name of the song"));
        commandData.add(Commands.slash("setvolume", "imposta il volume del bot").addOption(OptionType.INTEGER, "volume", "il valore del volume"));

        event.getGuild().updateCommands().addCommands(commandData).queue();
    }
}
