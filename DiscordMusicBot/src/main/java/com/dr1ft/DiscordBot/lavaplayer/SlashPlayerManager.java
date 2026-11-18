package com.dr1ft.DiscordBot.lavaplayer;

import com.sedmelluq.discord.lavaplayer.player.AudioLoadResultHandler;
import com.sedmelluq.discord.lavaplayer.player.AudioPlayerManager;
import com.sedmelluq.discord.lavaplayer.player.DefaultAudioPlayerManager;
import com.sedmelluq.discord.lavaplayer.source.AudioSourceManagers;
import com.sedmelluq.discord.lavaplayer.tools.FriendlyException;
import com.sedmelluq.discord.lavaplayer.track.AudioPlaylist;
import com.sedmelluq.discord.lavaplayer.track.AudioTrack;
import net.dv8tion.jda.api.entities.Guild;
import net.dv8tion.jda.api.entities.channel.unions.MessageChannelUnion;
import net.dv8tion.jda.api.events.interaction.command.SlashCommandInteractionEvent;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class SlashPlayerManager {

    private static SlashPlayerManager INSTANCE;
    private final Map<Long, GuildMusicManager> musicManagers;
    private final AudioPlayerManager audioPlayerManager;

    public SlashPlayerManager() {
        this.musicManagers = new HashMap<>();
        this.audioPlayerManager = new DefaultAudioPlayerManager();

        AudioSourceManagers.registerRemoteSources(this.audioPlayerManager);
        AudioSourceManagers.registerLocalSource(this.audioPlayerManager);
    }

    public GuildMusicManager getMusicManager (Guild guild) {
        return this.musicManagers.computeIfAbsent(guild.getIdLong(), (guildId) -> {
           final GuildMusicManager guildMusicManager = new GuildMusicManager(this.audioPlayerManager);
           guild.getAudioManager().setSendingHandler(guildMusicManager.getSendHandler());
           return guildMusicManager;
        });
    }

    public void loadAudioFile (Guild guild, String audioFile, SlashCommandInteractionEvent event) {
        final GuildMusicManager musicManager = this.getMusicManager(guild);

    }

    public void loadAndPlay(Guild guild, String trackUrl, SlashCommandInteractionEvent event) {
        final GuildMusicManager musicManager = this.getMusicManager(guild);
        this.audioPlayerManager.loadItemOrdered(musicManager, trackUrl, new AudioLoadResultHandler() {
            @Override
            public void trackLoaded(AudioTrack audioTrack) {
                musicManager.scheduler.queue(audioTrack);
                StringBuilder message = new StringBuilder();
                message.append("Track Loaded: ").append(audioTrack.getInfo().title).append(" from ").append(audioTrack.getInfo().author);
                event.reply(message.toString()).queue();
            }

            @Override
            public void playlistLoaded(AudioPlaylist audioPlaylist) {
                final List<AudioTrack> tracks = audioPlaylist.getTracks();
                if(!tracks.isEmpty()) {
                    musicManager.scheduler.queue(tracks.get(0));
                    StringBuilder message = new StringBuilder();
                    message.append("Track Loaded: ").append(audioPlaylist.getSelectedTrack().getInfo().title).append(" from ").append(audioPlaylist.getSelectedTrack().getInfo().author);
                    event.reply(message.toString()).queue();
                }
            }

            @Override
            public void noMatches() {

                event.reply("No Matches for this track-link").queue();
                if (!musicManager.audioPlayer.isPaused()) {

                } else {
                    musicManager.audioPlayer.destroy();
                    event.getMember().getGuild().getAudioManager().closeAudioConnection();
                }
            }

            @Override
            public void loadFailed(FriendlyException e) {
                event.reply("Failed Loading").queue();
                System.out.println(e);
                if (!musicManager.audioPlayer.isPaused()) {

                } else {
                    musicManager.audioPlayer.destroy();
                    event.getMember().getGuild().getAudioManager().closeAudioConnection();
                }
            }
        }
        );
    }

    public void skipTrack (Guild guild, SlashCommandInteractionEvent event) {
        final GuildMusicManager musicManager = this.getMusicManager(guild);
        try {
            getMusicManager(guild).scheduler.nextTrack();
            event.reply("Now playing: " + musicManager.audioPlayer.getPlayingTrack().getInfo().title + "by " + musicManager.audioPlayer.getPlayingTrack().getInfo().author).queue();
        } catch (RuntimeException e) {
            event.reply("Non ci sono altre canzoni in coda").queue();
        }
    }
    public void resumeTrack (Guild guild ) {
        getMusicManager(guild).scheduler.resume();
    }
    public void killPlayer (Guild guild) {
        getMusicManager(guild).audioPlayer.destroy();
    }

    public void setVolume (int value, Guild guild, SlashCommandInteractionEvent event) {
        int maxValue = 100;
        if (value <= maxValue) {
            getMusicManager(guild).audioPlayer.setVolume(value);
            event.reply("Volume impostato al valore: " + value).queue();
        } else {
            event.reply("valore troppo alto!, il massimo vaolre è " + maxValue).queue();
        }
    }



    /* public void playFile(String filePath, Guild guild) {
        getMusicManager(guild).pla

    } */


    public static SlashPlayerManager getINSTANCE () {
        if(INSTANCE == null) {
            INSTANCE = new SlashPlayerManager();
        }
        return INSTANCE;
    }
}
