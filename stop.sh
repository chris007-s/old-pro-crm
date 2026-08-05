#!/bin/bash

echo "Stopping Old Pro CRM..."

# Stop desktop CRM
pkill -f "old_pro_crmWithAutoSpeak.py" && echo "✅ Desktop CRM stopped" || echo "⚠️  Desktop CRM was not running"

# Stop web server
pkill -f "old_pro_web.py" && echo "✅ Web server stopped" || echo "⚠️  Web server was not running"

# Stop ngrok
pkill -f "ngrok" && echo "✅ ngrok stopped" || echo "⚠️  ngrok was not running"

echo "All stopped."
