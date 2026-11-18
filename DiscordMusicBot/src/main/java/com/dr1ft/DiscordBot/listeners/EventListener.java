package com.dr1ft.DiscordBot.listeners;

import com.dr1ft.DiscordBot.lavaplayer.PlayerManager;
import com.dr1ft.DiscordBot.lavaplayer.TrackScheduler;
import io.github.cdimascio.dotenv.Dotenv;
import net.dv8tion.jda.api.entities.Guild;
import net.dv8tion.jda.api.entities.Member;
import net.dv8tion.jda.api.entities.User;
import net.dv8tion.jda.api.entities.Widget;
import net.dv8tion.jda.api.entities.channel.concrete.VoiceChannel;
import net.dv8tion.jda.api.entities.channel.unions.AudioChannelUnion;
import net.dv8tion.jda.api.events.Event;
import net.dv8tion.jda.api.events.interaction.command.SlashCommandInteractionEvent;
import net.dv8tion.jda.api.events.message.MessageReceivedEvent;
import net.dv8tion.jda.api.events.message.react.MessageReactionAddEvent;
import net.dv8tion.jda.api.events.message.react.MessageReactionRemoveEvent;
import net.dv8tion.jda.api.hooks.ListenerAdapter;
import net.dv8tion.jda.api.managers.AudioManager;

import java.net.MalformedURLException;
import java.net.URI;
import java.net.URISyntaxException;
import java.net.URL;


public class EventListener extends ListenerAdapter {
    private String prefix = "-";
    public EventListener (String prefix) {
        this.prefix = prefix;
    }
    public EventListener() {
    }

    @Override
    public void onMessageReactionAdd(MessageReactionAddEvent event) {
        User user = event.getUser();
        String reaction = event.getReaction().getEmoji().getFormatted();
        String channelMention = event.getChannel().getAsMention();
        String jumpLink = event.getJumpUrl();
        String message = user.getAsTag() + " Reacted to " + reaction + " in " + channelMention ;
        event.getChannel().sendMessage(message).queue();
    }

    public boolean isurl (String url) {
        try {
            new URL(url);
            return true;
        } catch (MalformedURLException e) {
            return false;
        }
    }

    @Override
    public void onMessageReceived(MessageReceivedEvent event) {
        String message = event.getMessage().getContentRaw();
        if (message.startsWith(prefix) && message.contains("play")) {
            String msg =  String.join(" ", event.getMessage().getContentRaw());
            String[] cmdContent = msg.split(" ");
            String url = cmdContent[1];
            System.out.println(url);
            Member utente = event.getMember();
            String link = "";
            if(utente.getVoiceState().inAudioChannel()) {
               final Guild guild = utente.getGuild();
               final VoiceChannel channel = (VoiceChannel) utente.getVoiceState().getChannel();
               final AudioManager audioMgr = guild.getAudioManager();
               audioMgr.openAudioConnection(channel);
               if(isurl(url)) {
                   link = "ytsearch: " + url + " audio";
               }
               PlayerManager.getINSTANCE().loadAndPlay(guild, link, event.getChannel());
            }
        }
        if (message.startsWith(prefix) && message.contains("dagie")) {
            System.out.println("dagie");
            event.getChannel().sendMessage("tabee").queue();
        }

        if (message.startsWith(prefix) && message.contains("skip")) {
            final Member utente = event.getMember();
            final Guild guild = utente.getGuild();
            final AudioManager audioMgr = guild.getAudioManager();
            PlayerManager.getINSTANCE().skipTrack(guild, event.getChannel());
        }

        if (message.startsWith(prefix) && message.contains("pause")) {
            final Member utente = event.getMember();
            final Guild guild = utente.getGuild();
            final AudioManager audioMgr = guild.getAudioManager();
            PlayerManager.getINSTANCE().pauseTrack(guild);
        }

        if (message.startsWith(prefix) && message.contains("resume")) {
            final Member utente = event.getMember();
            final Guild guild = utente.getGuild();
            final AudioManager audioMgr = guild.getAudioManager();
            PlayerManager.getINSTANCE().resumeTrack(guild);
        }

        if (message.startsWith(prefix) && message.contains("stop")) {
            final Member utente = event.getMember();
            final Guild guild = utente.getGuild();
            final AudioManager audioMgr = guild.getAudioManager();
            PlayerManager.getINSTANCE().killPlayer(guild);
            audioMgr.closeAudioConnection();
        }
        /*
        if (message.startsWith(prefix) && message.contains("myworstnightmare")) {
            final Member utente = event.getMember();
            final Guild guild = utente.getGuild();
            final AudioManager audioMgr = guild.getAudioManager();
            PlayerManager.getINSTANCE().loadAndPlay(guild, );
        } */
    }

    @Override
    public void onSlashCommandInteraction(SlashCommandInteractionEvent event) {

        if (event.getName().equals("ping")) {
            event.getChannel().sendMessage("pong");
        }
        super.onSlashCommandInteraction(event);
    }
}
