from __future__ import annotations

import os
import secrets
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


APP_ROOT = Path("/home/pianwei/apps/due-diligence-assistant")
NGINX_ROOT = Path("/home/pianwei/Dify/dify/docker/nginx/conf.d")
PASSWORD_FILE = APP_ROOT / "ops-basic-auth-password.txt"
HTPASSWD_FILE = NGINX_ROOT / "due-diligence.htpasswd"
MARKER = "# BEGIN due-diligence-assistant"

LOCATION_BLOCK = """    # BEGIN due-diligence-assistant
    location = /due-diligence {
      return 301 /due-diligence/;
    }

    location ^~ /due-diligence/ops {
      auth_basic "Due Diligence Operations";
      auth_basic_user_file /etc/nginx/conf.d/due-diligence.htpasswd;
      proxy_pass http://due-diligence-assistant:8000/ops;
      include proxy.conf;
    }

    location ^~ /due-diligence/api/v1/ops/ {
      auth_basic "Due Diligence Operations";
      auth_basic_user_file /etc/nginx/conf.d/due-diligence.htpasswd;
      proxy_pass http://due-diligence-assistant:8000/api/v1/ops/;
      include proxy.conf;
    }

    location ^~ /due-diligence/ {
      proxy_pass http://due-diligence-assistant:8000/;
      include proxy.conf;
    }
    # END due-diligence-assistant

"""


def ensure_credentials() -> None:
    if HTPASSWD_FILE.exists():
        return
    password = secrets.token_urlsafe(18)
    PASSWORD_FILE.write_text(password + "\n", encoding="utf-8")
    os.chmod(PASSWORD_FILE, 0o600)
    digest = subprocess.run(
        ["openssl", "passwd", "-apr1", "-stdin"],
        input=password,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    HTPASSWD_FILE.write_text(f"opsadmin:{digest}\n", encoding="utf-8")
    os.chmod(HTPASSWD_FILE, 0o644)


def insert_location(path: Path, backup_dir: Path) -> None:
    content = path.read_text(encoding="utf-8")
    if MARKER in content:
        updated = content.replace("      proxy_read_timeout 120s;\n", "")
        if updated != content:
            shutil.copy2(path, backup_dir / path.name)
            temporary = path.with_name(path.name + ".due-diligence.tmp")
            temporary.write_text(updated, encoding="utf-8")
            os.chmod(temporary, path.stat().st_mode & 0o777)
            os.replace(temporary, path)
        return
    needle = "    location / {\n"
    if needle not in content:
        raise RuntimeError(f"cannot find insertion point in {path}")
    shutil.copy2(path, backup_dir / path.name)
    updated = content.replace(needle, LOCATION_BLOCK + needle, 1)
    temporary = path.with_name(path.name + ".due-diligence.tmp")
    temporary.write_text(updated, encoding="utf-8")
    os.chmod(temporary, path.stat().st_mode & 0o777)
    os.replace(temporary, path)


def main() -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = APP_ROOT / "nginx-backups" / timestamp
    backup_dir.mkdir(parents=True, exist_ok=False)
    ensure_credentials()
    insert_location(NGINX_ROOT / "default.conf", backup_dir)
    insert_location(NGINX_ROOT / "default.conf.template", backup_dir)
    print(f"nginx_backup={backup_dir}")
    print(f"ops_username=opsadmin")
    print(f"ops_password_file={PASSWORD_FILE}")


if __name__ == "__main__":
    main()
