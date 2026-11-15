Source tapes/_common.tape
Output build/setup.mp4
Sleep 600ms
Type "docker compose up -d --wait db"
Sleep 400ms
Enter
Sleep 1500ms
Type "finagent --help"
Sleep 400ms
Enter
Sleep 2500ms
