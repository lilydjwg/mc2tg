# Usage

```sh
mkfifo /tmp/bot
tmux pipe-pane -IO -o -t 0:5.0 "TOKEN=XXX $PWD/mc2tg.py --logfile=/tmp/bot"
cat /tmp/bot
```
