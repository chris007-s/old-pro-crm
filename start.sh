#!/bin/bash

# Get the directory where this script lives
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Start web server if not already running
if ! pgrep -f "old_pro_web.py" > /dev/null; then
    echo "Starting web server..."
    python3 "$DIR/old_pro_web.py" &
    sleep 3
else
    echo "Web server already running"
fi

# Start ngrok if not already running
if ! pgrep -f "ngrok" > /dev/null; then
    echo "Starting ngrok tunnel..."
    ngrok http 5000 &
    sleep 3
else
    echo "ngrok already running"
fi

# Start desktop CRM
echo "Starting desktop CRM..."
python3 "$DIR/old_pro_crmWithAutoSpeak.py"
