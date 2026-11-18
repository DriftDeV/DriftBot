package com.dr1ft.DiscordBot.lavaplayer;

import com.sedmelluq.discord.lavaplayer.player.AudioPlayer;
import com.sedmelluq.discord.lavaplayer.player.event.AudioEventAdapter;
import com.sedmelluq.discord.lavaplayer.track.AudioTrack;
import com.sedmelluq.discord.lavaplayer.track.AudioTrackEndReason;
import java.util.concurrent.BlockingDeque;
import java.util.concurrent.LinkedBlockingDeque;

public class TrackScheduler extends AudioEventAdapter {

    public final AudioPlayer audioPlayer;
    public final BlockingDeque<AudioTrack> queue;

    private final SlashPlayerManager spm = new SlashPlayerManager();
    public TrackScheduler (AudioPlayer audioPlayer) {
        this.audioPlayer = audioPlayer;
        this.queue = new LinkedBlockingDeque<>();
    }

    @Override
    public void onTrackEnd(AudioPlayer player, AudioTrack track, AudioTrackEndReason endReason) {
        if (!this.queue.isEmpty()) {
            this.audioPlayer.startTrack(this.queue.poll(), false);
            System.out.println("going to next track "+ track.getInfo().toString());
        } else {
            this.audioPlayer.destroy();
            System.out.println("player killed no more track to play");
        }
        super.onTrackEnd(player, track, endReason);
    }

    public void queue(AudioTrack track) {
        if (!this.audioPlayer.startTrack(track, true)) {
            this.queue.offer(track);
        }
    }

    public void pause () {
        if (this.audioPlayer.isPaused() == false ) {
            this.audioPlayer.setPaused(true);
        }
    }

    public void resume () {
        if (this.audioPlayer.isPaused() == true ) {
            this.audioPlayer.setPaused(false);
        }
    }

    public void nextTrack() {
        if (!this.queue.isEmpty()) {
            this.audioPlayer.startTrack(this.queue.poll(), false);
        }
        else {
            throw new RuntimeException();
        }
    }
}
