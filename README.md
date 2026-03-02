# telegram-channel-downloader
A working telegram channel downloader.

I created this with anthropic because all of the other programs and scripts failed. Requires python 3.

Run with 'python3 telegram-downloader.py'.

If the channel is a forum (a channel with separate topics) it will put them into their own folders. If you want them downloaded into the same folder, use https://claude.ai/ to create a new one.

It also has parameters for:
ignore downloading files for mime types, part of the telegram api, (ie not just ignoring of .mp4)
ignore downloading files from specific topics
download to a flat folder versus folders for each topic
options to accept the telegram api id, api hash, and channel number in the parameters rather than in the configuration file 'tg_forum.session'.

These are needed for configuration:

# CONFIGURATION 
`API_ID =    55325        # Replace with your api_id from my.telegram.org`

`API_HASH = "5543234541322556"  # Replace with your api_hash from my.telegram.org`

`The forum group: use numeric ID like -1001234567890 or username like "mygroup". One can find the channel numerical ID at: https://web.telegram.org/ in the URL.`

`FORUM_ID =  -100045423230230
