"""Install the app's single daily collector; preserve unrelated crontab entries."""
from datetime import datetime, timezone
from pathlib import Path
import subprocess

root = '/home/deploy/steam-sale-ranker'
old = subprocess.run(['crontab', '-l'], capture_output=True, text=True, check=True).stdout
backup = Path('/home/deploy/backups-predeploy') / ('gamepromo-cron-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '.txt')
backup.parent.mkdir(parents=True, exist_ok=True)
backup.write_text(old, encoding='utf-8')
lines = [line for line in old.splitlines() if not (root in line and ('steam-gen' in line or 'gamepromo-refresh' in line))]
lines.append('0 3 * * * cd ' + root + ' && flock -n /tmp/gamepromo-refresh.lock timeout 9000 docker run --rm --entrypoint python -v steam_data:/app/data steam-gen:latest refresh_daily.py --pages 20 >> /var/backups/mesa20/steam-gen.log 2>&1')
subprocess.run(['crontab', '-'], input='\n'.join(lines) + '\n', text=True, check=True)
print('cron installed; backup=' + str(backup))
