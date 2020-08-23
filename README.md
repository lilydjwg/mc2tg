# Synchronize messages from minecraft server to Telegram and back

# Requirement

Your minecraft server is running inside tmux.

You need Python 3.8+ and all Python libraries in `requirements.txt` installed.

Currently the messages are in Simplified Chinese. Contributions for other
languages are welcome.

# Usage

Create your bot, make group messages accessible to it, add it to your group,
write a configuration file for this script (see `sample-config.toml`), figure
out the tmux pane your minecraft is running, and then run like this (paths
need to be absolute):

```sh
tmux pipe-pane -IO -o -t session:5.0 "$PWD/mc2tg.py -c $PWD/config.toml"
```

To get the log, you can use shell redirection. You can also create a named
pipe (fifo) with `mkfifo` if you don't want a ever-growing log file.

```sh
tmux pipe-pane -IO -o -t session:5.0 "$PWD/mc2tg.py -c $PWD/config.toml 2>/path/to/logfile"
```
