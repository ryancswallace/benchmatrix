Output ../assets/basic-demo.mp4
Output ../assets/basic-demo.webm

# cspell:ignore precmd RPROMPT

Require uv

Set Shell zsh
Set Width 1200
Set Height 900
Set FontSize 16
Set TypingSpeed 75ms
Set CursorBlink false

Hide
Type "precmd() { :; }; precmd_functions=(); PROMPT='❯ '; RPROMPT=''"
Enter
Type "rm -rf -- /tmp/bm-demo-base /tmp/bm-demo-candidate"
Enter
Type `clear; printf '\n  Build and compare a Python benchmark matrix\n\n'`
Enter
Show
Sleep 3s

Hide
Type "clear"
Enter
Show
Type "sed -n '1,120p' basic_demo.py"
Enter
Sleep 12s

Hide
Type `clear; printf '\n  Collect three baseline runs\n\n'`
Enter
Show
Sleep 3s

Hide
Type "clear"
Enter
Show
Type "uv run benchmatrix measure --runs 3 --output /tmp/bm-demo-base basic_demo.py"
Enter
Wait+Screen@120s /Overall: PASS/
Sleep 8s

Hide
Type `clear; printf '\n  Collect a deliberately slower candidate\n\n'`
Enter
Show
Sleep 3s

Hide
Type "clear"
Enter
Show
Type "BENCHMATRIX_DEMO_SLOWDOWN=1 uv run benchmatrix measure --runs 3 --output /tmp/bm-demo-candidate basic_demo.py"
Enter
Wait+Screen@120s /Overall: PASS/
Sleep 8s

Hide
Type `clear; printf '\n  Compare the repeated runs\n\n'`
Enter
Show
Sleep 3s

Set TypingSpeed 25ms
Hide
Type "clear"
Enter
Show
Type "uv run benchmatrix compare /tmp/bm-demo-base /tmp/bm-demo-candidate --threshold 25% --summary"
Enter
Wait+Screen@60s /Overall: FAIL/
Screenshot ../assets/basic-demo.png
Sleep 8s

Hide
Type "rm -rf -- /tmp/bm-demo-base /tmp/bm-demo-candidate"
Enter
