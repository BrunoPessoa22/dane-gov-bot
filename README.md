# Dane.gov.pl Automated CSV Uploader

Automates daily uploads of CSV files to the Polish government data portal (dane.gov.pl).

## Features

- 🔐 Secure login handling
- 📤 Automated CSV file upload
- 📅 Automatic date formatting in titles
- 🔄 Copies from latest resource to maintain metadata
- ⚙️ Configures "Znaki umowne" settings automatically
- 📝 Comprehensive logging
- 📸 Screenshots on success/failure for debugging

## Prerequisites

- Python 3.8 or higher
- A dane.gov.pl account with admin access

## Quick Start

### 1. Clone/Copy the Project

```bash
# Copy the project to your desired location
cp -r dane-gov-bot ~/dane-gov-bot
cd ~/dane-gov-bot
```

### 2. Run Setup

```bash
chmod +x setup.sh
./setup.sh
```

This will:
- Create a Python virtual environment
- Install all dependencies
- Install Playwright browser (Chromium)
- Create a `.env` file from template

### 3. Configure Credentials

Edit the `.env` file with your credentials:

```bash
nano .env
```

Update:
```
DANE_GOV_EMAIL=your_email@example.com
DANE_GOV_PASSWORD=your_password
CSV_FILE_PATH=/full/path/to/your/spreadsheet.csv
```

### 4. Test the Uploader

Run manually to verify everything works:

```bash
source venv/bin/activate
python dane_gov_uploader.py --csv-path /path/to/your/file.csv
```

For debugging (shows browser window):
```bash
python dane_gov_uploader.py --csv-path /path/to/your/file.csv
```

For production (headless, no browser window):
```bash
python dane_gov_uploader.py --csv-path /path/to/your/file.csv --headless
```

## Scheduling Daily Runs

### Option A: Using Cron (Linux/Mac)

1. Make the runner script executable:
```bash
chmod +x run_daily.sh
```

2. Open crontab:
```bash
crontab -e
```

3. Add a daily schedule (example: run at 8:00 AM every day):
```cron
0 8 * * * /full/path/to/dane-gov-bot/run_daily.sh
```

Common cron schedules:
- `0 8 * * *` - Every day at 8:00 AM
- `0 9 * * 1-5` - Weekdays at 9:00 AM
- `30 7 * * *` - Every day at 7:30 AM

### Option B: Using launchd (Mac - Recommended)

1. Create a launchd plist file:

```bash
mkdir -p ~/Library/LaunchAgents
cat > ~/Library/LaunchAgents/com.dane-gov.uploader.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.dane-gov.uploader</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>/Users/YOUR_USERNAME/dane-gov-bot/run_daily.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>8</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/YOUR_USERNAME/dane-gov-bot/logs/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/YOUR_USERNAME/dane-gov-bot/logs/launchd_error.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF
```

2. Replace `YOUR_USERNAME` with your actual username:
```bash
sed -i '' "s/YOUR_USERNAME/$(whoami)/g" ~/Library/LaunchAgents/com.dane-gov.uploader.plist
```

3. Load the schedule:
```bash
launchctl load ~/Library/LaunchAgents/com.dane-gov.uploader.plist
```

4. To test immediately:
```bash
launchctl start com.dane-gov.uploader
```

5. To unload/stop:
```bash
launchctl unload ~/Library/LaunchAgents/com.dane-gov.uploader.plist
```

### Option C: Using Task Scheduler (Windows)

1. Open Task Scheduler
2. Create a new Basic Task
3. Set trigger to "Daily" at your preferred time
4. Action: Start a program
   - Program: `C:\path\to\dane-gov-bot\venv\Scripts\python.exe`
   - Arguments: `dane_gov_uploader.py --csv-path "C:\path\to\your\file.csv" --headless`
   - Start in: `C:\path\to\dane-gov-bot`

## Using with Claude Code

You can also run this directly with Claude Code:

```bash
# Navigate to the project
cd ~/dane-gov-bot

# Run with Claude Code
claude code "Run the dane_gov_uploader.py script with my CSV file at /path/to/file.csv"
```

Or create an MCP tool for it.

## File Structure

```
dane-gov-bot/
├── dane_gov_uploader.py  # Main upload script
├── requirements.txt      # Python dependencies
├── setup.sh             # Setup script
├── run_daily.sh         # Daily runner for cron
├── .env.template        # Environment variables template
├── .env                 # Your credentials (git-ignored)
├── logs/                # Log files
│   └── upload_YYYYMMDD.log
└── README.md            # This file
```

## Troubleshooting

### Login Failed
- Verify credentials in `.env`
- Try running without `--headless` to see what's happening
- Check if the website structure has changed

### Element Not Found
- The website may have been updated
- Check screenshots in the project directory
- Run without `--headless` to debug

### Browser Won't Start
- Reinstall Playwright browsers: `playwright install chromium`
- Install system dependencies: `playwright install-deps chromium`

### Cron Not Running
- Check cron logs: `grep CRON /var/log/syslog`
- Ensure full paths are used in crontab
- Check that the virtual environment activates correctly

## Logs

Logs are stored in the `logs/` directory with format:
- `upload_YYYYMMDD.log` - Daily upload logs

Logs older than 30 days are automatically deleted.

## Security Notes

⚠️ **Important Security Considerations:**

1. **Never commit `.env` to git** - Add it to `.gitignore`
2. **Use environment variables** for credentials in production
3. **Restrict file permissions**: `chmod 600 .env`
4. **Consider using a secrets manager** for production deployments

## Support

If you encounter issues:
1. Check the logs in `logs/` directory
2. Review screenshots generated on errors
3. Run manually without `--headless` to debug visually

## License

MIT License
