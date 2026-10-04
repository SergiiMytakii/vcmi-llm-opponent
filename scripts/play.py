"""Create a separate game profile and launch the developer VCMI distribution."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from create_scenario import write_map

ROOT = Path(__file__).resolve().parents[1]
MARKER = 'external-ai-profile.json'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'controller'))
from codex import resolve_executable


@contextmanager
def profile_lock(profile):
    # OS locks disappear when the launcher exits, including after a crash.
    with (profile / 'launcher.lock').open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'\0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError('this profile is already in use by another launcher') from error
        yield


def preflight(engine, profile, codex):
    env = os.environ.copy()
    for key in ('DYLD_INSERT_LIBRARIES', 'OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENAI_BASE_URL',
                'VCMI_PLAYTEST_RUN', 'VCMI_PLAYTEST_DECISION_DIR', 'VCMI_PLAYTEST_PROMPT',
                'VCMI_PLAYTEST_KNOWLEDGE'):
        env.pop(key, None)
    env.update(VCMI_PROFILE_DIR=str(profile), VCMI_EXTERNAL_AI_EXECUTABLE=sys.executable,
               VCMI_EXTERNAL_AI_SCRIPT=str(ROOT / 'controller/main.py'), VCMI_CODEX_EXECUTABLE=str(codex),
               VCMI_EXPERIENCE_MODE='learn')
    # Help exits before VCMI initializes directories; an installed/older game
    # must be rejected here, without ever opening its normal profile.
    result = subprocess.run([str(engine), '--help'], cwd=engine.parent, env=env,
                            capture_output=True, timeout=10)
    if result.returncode or b'VCMI_PROFILE_DIR' not in result.stdout:
        raise ValueError('engine lacks native profile isolation; use our rebuilt VCMI executable')
    result = subprocess.run([str(engine), '--version'], cwd=engine.parent, env=env,
                            capture_output=True, text=True, encoding='utf-8', timeout=10)
    paths = dict(line.strip().split(':', 1) for line in result.stdout.splitlines()
                 if line.strip().startswith('user ') and ':' in line)
    for label, suffix in (('user data', ''), ('user cache', 'cache'), ('user config', 'config'),
                          ('user logs', 'logs'), ('user saves', 'Saves'), ('user extracted', 'cache/extracted')):
        if result.returncode or paths.get(label, '').strip() != str(profile / suffix):
            raise ValueError('engine writable paths do not match the separate profile')
    version = subprocess.run([str(codex), '--version'], env=env, capture_output=True, timeout=5)
    if version.returncode or version.stdout.decode().strip() != 'codex-cli 0.160.0':
        raise ValueError('requires Codex CLI 0.160.0')
    login = subprocess.run([str(codex), 'login', 'status'], env=env, capture_output=True, timeout=10)
    if login.returncode or b'chatgpt' not in (login.stdout + login.stderr).lower():
        # Never print raw authentication diagnostics: some CLI versions reveal key prefixes.
        raise ValueError('ChatGPT subscription login required; run codex login first')
    return env


def play(args):
    profile = args.profile.expanduser().resolve()
    marker = profile / MARKER
    if not marker.is_file() or json.loads(marker.read_text(encoding='utf-8')) != {'version': 1, 'scenario': 'Maps/LandDuel-v1.vmap'}:
        raise ValueError('profile was not created by play.py init')
    if any(p.is_symlink() for p in profile.rglob('*')):
        raise ValueError('profile contains links to other directories')
    engine = args.engine.expanduser().resolve()
    if not engine.is_file():
        raise ValueError('engine executable is missing')
    codex = resolve_executable(args.codex)
    with profile_lock(profile):
        env = preflight(engine, profile, codex)
        if args.check:
            print('Ready: isolated profile, Codex CLI 0.160.0, ChatGPT login, gpt-6.1-sol / medium.')
            return 0
        from playtesting.runs import write_json
        settings_path = profile / 'config/settings.json'
        settings = json.loads(settings_path.read_text(encoding='utf-8'))
        settings.setdefault('ai', {}).update(adventureAlliedAI='ExternalAI', adventureEnemyAI='ExternalAI')
        settings.setdefault('general', {}).update(lastMap='MAPS/LANDDUEL-V1', saveFrequency=1)
        write_json(settings_path, settings)
        command = [str(engine), '--nointro', '--disable-video']
        if args.mode == 'spectator':
            command += ['--onlyAI', '--testmap', 'Maps/LandDuel-v1.vmap', '--spectate',
                        '--spectate-skip-battle-result', '--ai', 'ExternalAI', '--ai', 'Nullkiller2']
        else:
            print('New game: select External AI - Land Duel, red human / blue AI. Blue uses ExternalAI.', flush=True)
        print('Profile:', profile, flush=True)
        with (profile / 'logs/launcher.log').open('ab') as log:
            if os.name == 'nt':
                from windows_process import run
                return run(command, cwd=engine.parent, env=env, log=log,
                           cleanup_path=profile / 'logs/cleanup.json')
            child = subprocess.Popen(command, cwd=engine.parent, env=env, stdout=log,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            try:
                return child.wait()
            except KeyboardInterrupt:
                return 130
            finally:
                from playtesting.launcher import terminate_group
                terminate_group(child, profile / 'logs/cleanup.json')


def initialize(data, profile):
    data, profile = data.expanduser().resolve(), profile.expanduser().resolve()
    if not data.is_dir() or not any(p.suffix.lower() == '.lod' for p in data.iterdir()):
        raise ValueError('--data must point to your licensed Heroes III Data directory containing .lod files')
    if profile == data or profile.is_relative_to(data):
        raise ValueError('profile must be separate from the source data')
    if any(p.is_symlink() for p in data.rglob('*')):
        raise ValueError('data must contain real files, not links to another directory')
    profile.mkdir(parents=True, exist_ok=False, mode=0o700)
    try:
        shutil.copytree(data, profile / 'Data')
        (profile / 'Maps').mkdir()
        (profile / 'config').mkdir()
        write_map(profile / 'Maps/LandDuel-v1.vmap')
        settings = {'ai': {'adventureAlliedAI': 'ExternalAI', 'adventureEnemyAI': 'ExternalAI'},
                    'general': {'lastMap': 'MAPS/LANDDUEL-V1', 'lastDifficulty': 4, 'saveFrequency': 1},
                    'video': {'fullscreen': False}}
        (profile / 'config/settings.json').write_text(json.dumps(settings, indent=2) + '\n', encoding='utf-8')
        (profile / MARKER).write_text(json.dumps({'version': 1, 'scenario': 'Maps/LandDuel-v1.vmap'}) + '\n', encoding='utf-8')
    except BaseException:
        shutil.rmtree(profile)
        raise
    print('Created separate profile:', profile)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('init', help='Copy your game data into a new private profile')
    create.add_argument('--data', type=Path, required=True)
    create.add_argument('--profile', type=Path, required=True)
    run = commands.add_parser('run', help='Launch a separate profile with Codex as opponent')
    run.add_argument('--profile', type=Path, required=True)
    run.add_argument('--engine', type=Path, required=True)
    run.add_argument('--mode', choices=('human', 'spectator'), required=True)
    run.add_argument('--codex', help='Path to Codex CLI, if it is not on PATH')
    run.add_argument('--check', action='store_true', help='Check isolation and login without launching the game')
    args = parser.parse_args()
    try:
        if args.command == 'init':
            initialize(args.data, args.profile)
        else:
            return play(args)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print('play:', error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
