package com.dr1ft.DiscordBot;

import com.dr1ft.DiscordBot.Commands.CommandManager;
import com.dr1ft.DiscordBot.Commands.PlayerCommands;
import com.dr1ft.DiscordBot.listeners.EventListener;
import io.github.cdimascio.dotenv.Dotenv;
import net.dv8tion.jda.api.JDA;
import net.dv8tion.jda.api.OnlineStatus;
import net.dv8tion.jda.api.entities.Activity;
import net.dv8tion.jda.api.requests.GatewayIntent;
import net.dv8tion.jda.api.sharding.DefaultShardManagerBuilder;
import net.dv8tion.jda.api.sharding.ShardManager;


public class DiscordBot {
    private final Dotenv config;
    private final ShardManager shardManager;
    public DiscordBot() {
        config = Dotenv.configure().load();
        String token = config.get("TOKEN");
        String prefix = config.get("PREFIX");
        DefaultShardManagerBuilder builder = DefaultShardManagerBuilder.createDefault(token);
        builder.setStatus(OnlineStatus.ONLINE);
        builder.setActivity(Activity.watching("Dr1ft"));
        builder.enableIntents(GatewayIntent.GUILD_MEMBERS);
        builder.enableIntents(GatewayIntent.MESSAGE_CONTENT);
        shardManager = builder.build();
        shardManager.addEventListener(new EventListener(prefix), new CommandManager(), new PlayerCommands());
    }

    public ShardManager getShardManager() {
        return shardManager;
    }
}
