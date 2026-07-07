"""
Run all Celery workers and beat scheduler.

Usage:
    python run_celery.py              # Start everything
    python run_celery.py --workers    # Workers only
    python run_celery.py --beat       # Beat only
    python run_celery.py --stop       # Stop all running Celery processes

On Windows, Celery requires --pool=solo (used automatically).
Each worker logs to logs/celery/<queue>.log.
"""

import os
import sys
import time
import subprocess
import argparse
from pathlib import Path
from typing import List

PROJECT_DIR = Path(__file__).resolve().parent
LOG_DIR = PROJECT_DIR / 'logs' / 'celery'
LOG_DIR.mkdir(parents=True, exist_ok=True)

os.chdir(str(PROJECT_DIR))

# Force use of venv Python
VENV_PYTHON = PROJECT_DIR / 'venv' / 'Scripts' / 'python.exe'
if VENV_PYTHON.exists():
    sys.executable = str(VENV_PYTHON)

# Suppress Celery 6.0 deprecation warning about broker_connection_retry
os.environ.setdefault('CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP', 'true')

CELERY_APP = 'config'

QUEUES: List[tuple] = [
    ('email_polling',  1),   # Single worker to prevent duplicate processing
    ('ai_processing',  1),
    ('email_dispatch', 1),
    ('housekeeping',   1),
]

processes: List[subprocess.Popen] = []


def _open_log(name: str):
    return open(LOG_DIR / f'{name}.log', 'a', buffering=1)


def start_worker(queue: str, concurrency=None) -> subprocess.Popen:
    label = f'worker:{queue}'
    # Use venv Python explicitly
    python_exe = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
    cmd = [
        python_exe, '-m', 'celery', '-A', CELERY_APP, 'worker',
        '--pool=solo', '-Q', queue, '--loglevel=info',
    ]
    if concurrency:
        cmd.extend(['--concurrency', str(concurrency)])
    log = _open_log(queue)
    print(f'  [{label}] logs/{queue}.log')
    return subprocess.Popen(
        cmd,
        stdout=log,
        stderr=subprocess.STDOUT,
    )


def start_beat() -> subprocess.Popen:
    log = _open_log('beat')
    print('  [beat]       logs/beat.log')
    # Use venv Python explicitly
    python_exe = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
    return subprocess.Popen(
        [python_exe, '-m', 'celery', '-A', CELERY_APP, 'beat',
         '--loglevel=info'],
        stdout=log,
        stderr=subprocess.STDOUT,
    )


def stop_all():
    print('Stopping all Celery processes ...')
    subprocess.run(['taskkill', '/f', '/im', 'celery.exe'],
                   capture_output=True)
    print('Done.')


def main():
    parser = argparse.ArgumentParser(description='Run Celery workers and beat')
    parser.add_argument('--workers', action='store_true',
                        help='Start workers only')
    parser.add_argument('--beat', action='store_true',
                        help='Start beat only')
    parser.add_argument('--stop', action='store_true',
                        help='Stop all Celery processes')
    args = parser.parse_args()

    if args.stop:
        stop_all()
        return

    start_all = not args.workers and not args.beat

    try:
        if start_all or args.workers:
            print('Starting Celery workers:')
            for queue, concurrency in QUEUES:
                proc = start_worker(queue, concurrency)
                processes.append(proc)

        if start_all or args.beat:
            print('Starting Celery beat:')
            proc = start_beat()
            processes.append(proc)

        print(f'\nAll processes running. Logs written to {LOG_DIR}')
        print('Press Ctrl+C to stop.\n')

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print('\nShutting down ...')
        for proc in processes:
            proc.terminate()
        for proc in processes:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        print('All processes stopped.')


if __name__ == '__main__':
    main()
