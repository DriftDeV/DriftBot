package com.dr1ft.DiscordBot.Commands;
import com.dr1ft.DiscordBot.lavaplayer.PlayerManager;
import com.dr1ft.DiscordBot.lavaplayer.SlashPlayerManager;
import com.dr1ft.DiscordBot.listeners.EventListener;
import net.dv8tion.jda.api.entities.Guild;
import net.dv8tion.jda.api.entities.Member;
import net.dv8tion.jda.api.entities.Message;
import net.dv8tion.jda.api.entities.channel.concrete.VoiceChannel;
import net.dv8tion.jda.api.events.interaction.command.SlashCommandInteractionEvent;
import net.dv8tion.jda.api.hooks.ListenerAdapter;
import net.dv8tion.jda.api.interactions.commands.OptionMapping;
import net.dv8tion.jda.api.managers.AudioManager;

public class PlayerCommands extends CommandManager {
    private EventListener eventListener = new EventListener();

    @Override
    public void onSlashCommandInteraction(SlashCommandInteractionEvent event) {
        if (event.getName().equals("play")) {
            String url = "";
            Member utente = event.getMember();
            String link = "";
            boolean exceptionThrown = false;
            try {
                url = event.getOption("url").getAsString();
            } catch (NullPointerException e) {
                event.reply("Nessun argomento dato").queue();
                exceptionThrown = true;
            }
            System.out.println(url);
            if (utente.getVoiceState().inAudioChannel() && exceptionThrown == false) {
                final Guild guild = utente.getGuild();
                final VoiceChannel channel = (VoiceChannel) utente.getVoiceState().getChannel();
                final AudioManager audioMgr = guild.getAudioManager();
                audioMgr.openAudioConnection(channel);
                if (eventListener.isurl(url) == false) {
                    link = "ytsearch: " + url + " audio";
                } else {
                    link = url;
                }
                System.out.println(link);
                SlashPlayerManager.getINSTANCE().loadAndPlay(guild, link, event);
            }
        }


        else if (event.getName().equals("stop")) {
            final Member utente = event.getMember();
            final Guild guild = utente.getGuild();
            final AudioManager audioMgr = guild.getAudioManager();
            PlayerManager.getINSTANCE().killPlayer(guild);
            event.reply("Traccia stoppata").queue();
            audioMgr.closeAudioConnection();
        }

        else if (event.getName().equals("skip")) {
            final Member utente = event.getMember();
            final Guild guild = utente.getGuild();
            SlashPlayerManager.getINSTANCE().skipTrack(guild, event);
        }

        else if (event.getName().equals("pause")) {
            final Member utente = event.getMember();
            final Guild guild = utente.getGuild();
            event.reply("Traccia in pausa").queue();
            PlayerManager.getINSTANCE().pauseTrack(guild);
        }

        else if (event.getName().equals("resume")) {
            final Member utente = event.getMember();
            final Guild guild = utente.getGuild();
            event.reply("Traccia in riproduzione").queue();
            SlashPlayerManager.getINSTANCE().resumeTrack(guild);
        }

        else if (event.getName().equals("setvolume")) {
            final Member utente = event.getMember();
            final Guild guild = utente.getGuild();
            int value = event.getOption("volume").getAsInt();
            SlashPlayerManager.getINSTANCE().setVolume(value ,guild, event);
            }
        }
    }
